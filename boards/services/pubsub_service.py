"""
PubSubService — wrapper do RabbitMQ (pika) usado em dois papéis:

1) **Producer** (dentro do processo web/gunicorn):
   Publica eventos serializados em JSON no exchange configurado toda vez que
   algo muda no domínio (card movido, coluna criada, notificação, etc.).
   A publicação é *best-effort*: se o broker estiver fora, loga e segue.
   Nunca derruba request.

2) **Consumer** (dentro do management command `rabbit_bridge`, processo
   separado): `start_consuming()` fica bloqueado aguardando mensagens e
   chama o callback fornecido.

A separação é importante porque o pika usa conexões bloqueantes e *não é
thread-safe*. No processo web, usamos publishes curtos e reconectamos quando
a conexão cai. No processo bridge, uma única conexão fica aberta para sempre.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import threading
import time
from typing import Any, Callable, Optional

import pika
from django.conf import settings

# Logger geral (mantém compat com mensagens antigas que iam pro root)
logger = logging.getLogger(__name__)

# Logger dedicado a RabbitMQ — vai para logs/rabbitmq.log (ver settings.LOGGING).
# Toda atividade de pub/sub passa por aqui: conexão, publish, fail, close.
rmq_logger = logging.getLogger("nossotrello.pubsub")

_HOSTNAME = socket.gethostname()


class PubSubService:
    """
    Wrapper enxuto do pika. Thread-local para permitir uso seguro no gunicorn
    em modo gthread (cada thread tem sua própria conexão).
    """

    _local = threading.local()

    # ------------------------------------------------------------------
    # Construção lazy da conexão
    # ------------------------------------------------------------------
    @classmethod
    def _connect(cls) -> Optional[pika.BlockingConnection]:
        if not getattr(settings, "PUBSUB_ENABLED", False):
            return None

        existing = getattr(cls._local, "connection", None)
        if existing is not None and existing.is_open:
            return existing

        t0 = time.monotonic()
        rmq_logger.info(
            "connect.attempt host=%s:%s vhost=%s user=%s exchange=%s host_id=%s pid=%s",
            settings.RABBITMQ_HOST,
            settings.RABBITMQ_PORT,
            settings.RABBITMQ_VHOST,
            settings.RABBITMQ_USER,
            settings.RABBITMQ_EXCHANGE,
            _HOSTNAME,
            os.getpid(),
        )
        try:
            credentials = pika.PlainCredentials(
                settings.RABBITMQ_USER, settings.RABBITMQ_PASSWORD
            )
            parameters = pika.ConnectionParameters(
                host=settings.RABBITMQ_HOST,
                port=settings.RABBITMQ_PORT,
                virtual_host=settings.RABBITMQ_VHOST,
                credentials=credentials,
                heartbeat=30,
                blocked_connection_timeout=10,
                connection_attempts=2,
                retry_delay=1,
            )
            connection = pika.BlockingConnection(parameters)
            channel = connection.channel()
            channel.exchange_declare(
                exchange=settings.RABBITMQ_EXCHANGE,
                exchange_type="direct",
                durable=True,
            )
            cls._local.connection = connection
            cls._local.channel = channel
            rmq_logger.info(
                "connect.ok host=%s:%s vhost=%s exchange=%s took_ms=%.1f",
                settings.RABBITMQ_HOST,
                settings.RABBITMQ_PORT,
                settings.RABBITMQ_VHOST,
                settings.RABBITMQ_EXCHANGE,
                (time.monotonic() - t0) * 1000.0,
            )
            return connection
        except Exception as exc:  # noqa: BLE001
            rmq_logger.warning(
                "connect.fail host=%s:%s vhost=%s err=%s:%s took_ms=%.1f",
                settings.RABBITMQ_HOST,
                settings.RABBITMQ_PORT,
                settings.RABBITMQ_VHOST,
                type(exc).__name__,
                exc,
                (time.monotonic() - t0) * 1000.0,
                exc_info=True,
            )
            cls._local.connection = None
            cls._local.channel = None
            return None

    @classmethod
    def _channel(cls):
        conn = cls._connect()
        if conn is None:
            return None
        return getattr(cls._local, "channel", None)

    # ------------------------------------------------------------------
    # Producer API
    # ------------------------------------------------------------------
    @classmethod
    def publish(cls, data: dict[str, Any]) -> bool:
        """
        Publica `data` (dict serializável) no exchange. Retorna True se a
        mensagem entrou no broker, False se caiu em no-op (degradação suave).
        NUNCA lança — o objetivo é não quebrar request por culpa do broker.
        """
        etype = (data or {}).get("type") or "unknown"

        if not getattr(settings, "PUBSUB_ENABLED", False):
            rmq_logger.debug("publish.skip reason=disabled type=%s", etype)
            return False

        channel = cls._channel()
        if channel is None:
            rmq_logger.warning(
                "publish.skip reason=no_channel type=%s board=%s user=%s",
                etype,
                data.get("board_id"),
                data.get("user_id"),
            )
            return False

        t0 = time.monotonic()
        try:
            body = json.dumps(data, default=str).encode("utf-8")
            channel.basic_publish(
                exchange=settings.RABBITMQ_EXCHANGE,
                routing_key=settings.RABBITMQ_ROUTING_KEY,
                body=body,
                properties=pika.BasicProperties(
                    content_type="application/json",
                    delivery_mode=2,  # persistente
                ),
            )
            rmq_logger.info(
                "publish.ok type=%s bytes=%d board=%s user=%s users=%s global=%s took_ms=%.1f",
                etype,
                len(body),
                data.get("board_id"),
                data.get("user_id"),
                len(data.get("user_ids") or []) if isinstance(data.get("user_ids"), (list, tuple)) else None,
                bool(data.get("global")),
                (time.monotonic() - t0) * 1000.0,
            )
            return True
        except Exception as exc:  # noqa: BLE001
            rmq_logger.warning(
                "publish.fail type=%s board=%s user=%s err=%s:%s took_ms=%.1f",
                etype,
                data.get("board_id"),
                data.get("user_id"),
                type(exc).__name__,
                exc,
                (time.monotonic() - t0) * 1000.0,
                exc_info=True,
            )
            # descarta conexão ruim; próxima publish tenta de novo
            try:
                conn = getattr(cls._local, "connection", None)
                if conn is not None:
                    conn.close()
                    rmq_logger.info("publish.fail.close_ok type=%s", etype)
            except Exception as close_exc:  # noqa: BLE001
                rmq_logger.debug(
                    "publish.fail.close_err type=%s err=%s:%s",
                    etype,
                    type(close_exc).__name__,
                    close_exc,
                )
            cls._local.connection = None
            cls._local.channel = None
            return False

    # ------------------------------------------------------------------
    # Consumer API (usado apenas pelo `rabbit_bridge`)
    # ------------------------------------------------------------------
    def start_consuming(
        self,
        queue_name: str,
        callback: Callable[[dict[str, Any]], None],
        *,
        banner: bool = True,
    ) -> None:
        """
        Blocking. Declara a fila, faz bind no routing_key e começa a consumir
        em loop infinito. `callback` recebe o payload já decodificado.
        """
        if not getattr(settings, "PUBSUB_ENABLED", False):
            raise RuntimeError(
                "PUBSUB_ENABLED é False — configure RABBITMQ_HOST/USER antes "
                "de iniciar o consumer."
            )

        rmq_logger.info(
            "consumer.connect.attempt host=%s:%s vhost=%s queue=%s exchange=%s rk=%s",
            settings.RABBITMQ_HOST,
            settings.RABBITMQ_PORT,
            settings.RABBITMQ_VHOST,
            queue_name,
            settings.RABBITMQ_EXCHANGE,
            settings.RABBITMQ_ROUTING_KEY,
        )

        credentials = pika.PlainCredentials(
            settings.RABBITMQ_USER, settings.RABBITMQ_PASSWORD
        )
        parameters = pika.ConnectionParameters(
            host=settings.RABBITMQ_HOST,
            port=settings.RABBITMQ_PORT,
            virtual_host=settings.RABBITMQ_VHOST,
            credentials=credentials,
            heartbeat=60,
            blocked_connection_timeout=30,
        )
        connection = pika.BlockingConnection(parameters)
        channel = connection.channel()
        rmq_logger.info("consumer.connect.ok queue=%s", queue_name)
        channel.exchange_declare(
            exchange=settings.RABBITMQ_EXCHANGE,
            exchange_type="direct",
            durable=True,
        )
        channel.queue_declare(
            queue=queue_name, exclusive=False, durable=True, auto_delete=False
        )
        channel.queue_bind(
            queue=queue_name,
            exchange=settings.RABBITMQ_EXCHANGE,
            routing_key=settings.RABBITMQ_ROUTING_KEY,
        )
        channel.basic_qos(prefetch_count=16)

        def _on_message(ch, method, properties, body):  # noqa: ANN001
            recv_t0 = time.monotonic()
            body_len = len(body or b"")
            try:
                payload = json.loads(body.decode("utf-8"))
            except Exception as exc:  # noqa: BLE001
                rmq_logger.exception(
                    "consumer.payload_invalid bytes=%d err=%s:%s",
                    body_len,
                    type(exc).__name__,
                    exc,
                )
                ch.basic_ack(delivery_tag=method.delivery_tag)
                return

            etype = (payload or {}).get("type") or "unknown"
            rmq_logger.info(
                "consumer.recv type=%s bytes=%d board=%s user=%s tag=%s",
                etype,
                body_len,
                (payload or {}).get("board_id"),
                (payload or {}).get("user_id"),
                method.delivery_tag,
            )

            try:
                callback(payload)
                rmq_logger.info(
                    "consumer.dispatch.ok type=%s took_ms=%.1f",
                    etype,
                    (time.monotonic() - recv_t0) * 1000.0,
                )
            except Exception as exc:  # noqa: BLE001
                rmq_logger.exception(
                    "consumer.callback_fail type=%s err=%s:%s took_ms=%.1f",
                    etype,
                    type(exc).__name__,
                    exc,
                    (time.monotonic() - recv_t0) * 1000.0,
                )
            finally:
                ch.basic_ack(delivery_tag=method.delivery_tag)

        channel.basic_consume(queue=queue_name, on_message_callback=_on_message)

        if banner:
            rmq_logger.info(
                'consumer.ready queue=%s exchange=%s rk=%s prefetch=16',
                queue_name,
                settings.RABBITMQ_EXCHANGE,
                settings.RABBITMQ_ROUTING_KEY,
            )

        try:
            channel.start_consuming()
        except Exception as exc:  # noqa: BLE001
            rmq_logger.warning(
                "consumer.loop_exit queue=%s err=%s:%s",
                queue_name,
                type(exc).__name__,
                exc,
                exc_info=True,
            )
            raise


# ----------------------------------------------------------------------
# Helpers de alto nível — usados pelo domínio (signals, views, services)
# ----------------------------------------------------------------------

def publish_event(event_type: str, **data: Any) -> bool:
    """
    Atalho padronizado: publica um evento com schema mínimo
    `{"type": ..., ...}`. Sempre use este helper em vez de chamar
    PubSubService.publish diretamente — centraliza o shape dos eventos.
    """
    payload = {"type": event_type, **data}
    return PubSubService.publish(payload)
