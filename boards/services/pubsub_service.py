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
import threading
from typing import Any, Callable, Optional

import pika
from django.conf import settings

logger = logging.getLogger(__name__)


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
            return connection
        except Exception:  # noqa: BLE001
            logger.warning(
                "PubSub: falha conectando ao RabbitMQ (%s:%s). "
                "Publicação vira no-op.",
                settings.RABBITMQ_HOST,
                settings.RABBITMQ_PORT,
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
        if not getattr(settings, "PUBSUB_ENABLED", False):
            return False

        channel = cls._channel()
        if channel is None:
            return False

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
            return True
        except Exception:  # noqa: BLE001
            logger.warning("PubSub: falha publicando %s", data.get("type"), exc_info=True)
            # descarta conexão ruim; próxima publish tenta de novo
            try:
                conn = getattr(cls._local, "connection", None)
                if conn is not None:
                    conn.close()
            except Exception:  # noqa: BLE001
                pass
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
            try:
                payload = json.loads(body.decode("utf-8"))
            except Exception:  # noqa: BLE001
                logger.exception("PubSub bridge: payload inválido; descartando")
                ch.basic_ack(delivery_tag=method.delivery_tag)
                return

            try:
                callback(payload)
            except Exception:  # noqa: BLE001
                logger.exception(
                    "PubSub bridge: callback falhou para type=%s",
                    (payload or {}).get("type"),
                )
            finally:
                ch.basic_ack(delivery_tag=method.delivery_tag)

        channel.basic_consume(queue=queue_name, on_message_callback=_on_message)

        if banner:
            logger.info(
                'PubSub bridge pronto. Aguardando mensagens em "%s" '
                '(exchange=%s routing_key=%s).',
                queue_name,
                settings.RABBITMQ_EXCHANGE,
                settings.RABBITMQ_ROUTING_KEY,
            )

        channel.start_consuming()


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
