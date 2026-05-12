"""
rabbit_bridge — processo que liga o RabbitMQ ao Channels.

Roda como container separado no docker-compose. Fica bloqueado em
`start_consuming` lendo mensagens do exchange `nossotrello` e, para cada
mensagem, faz um `group_send` no channel layer (Redis), o que acorda todos
os BoardConsumer/UserConsumer conectados no grupo correspondente e empurra
o payload pelo WebSocket.

Roteamento de eventos -> grupos do Channels:

- Eventos que carregam `board_id`   -> grupo `board_<id>`
- Eventos que carregam `user_id`    -> grupo `user_<id>`
- Eventos que carregam `user_ids`   -> broadcast para cada `user_<id>` da lista
- Eventos com `global: True`        -> grupo `presence_global` (todos logados)
- Eventos com ambos: entrega em *todos* os grupos relevantes.

O consumer é *idempotente* no sentido de que o browser não vê reenvios
de evento (o cliente pode ignorar duplicatas olhando para `version` ou
`event_id`, se presente). Aqui só empacotamos e propagamos.
"""

from __future__ import annotations

import logging
import signal
import sys
import time
from typing import Any

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.core.management.base import BaseCommand

from boards.services.pubsub_service import PubSubService

logger = logging.getLogger(__name__)
# Logger dedicado para inspeção do RabbitMQ — vai para logs/rabbitmq.log.
rmq_logger = logging.getLogger("nossotrello.pubsub")


class Command(BaseCommand):
    help = (
        "Consome eventos do RabbitMQ e os distribui via Channels (Redis) "
        "para os WebSocket consumers do nossotrello."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--queue",
            default=None,
            help="Nome da fila (default: settings.RABBITMQ_CONSUMER_QUEUE)",
        )

    # ------------------------------------------------------------------
    def handle(self, *args, **options):
        from django.conf import settings

        if not getattr(settings, "PUBSUB_ENABLED", False):
            self.stderr.write(
                "PUBSUB_ENABLED=False — confira RABBITMQ_HOST/USER no .env. "
                "Nada a fazer."
            )
            sys.exit(2)

        queue_name = options.get("queue") or settings.RABBITMQ_CONSUMER_QUEUE

        self.stdout.write(
            self.style.SUCCESS(
                f"rabbit_bridge iniciando | broker={settings.RABBITMQ_HOST}:"
                f"{settings.RABBITMQ_PORT} | exchange={settings.RABBITMQ_EXCHANGE} "
                f"| queue={queue_name}"
            )
        )

        self._install_signal_handlers()

        channel_layer = get_channel_layer()
        if channel_layer is None:
            self.stderr.write("CHANNEL_LAYERS não configurado. Abortando.")
            sys.exit(3)

        # Loop com reconexão: se a conexão Rabbit cair, dorme e tenta de novo.
        backoff = 1.0
        reconnect_count = 0
        while True:
            service = PubSubService()
            try:
                rmq_logger.info(
                    "bridge.start queue=%s reconnect_count=%d",
                    queue_name,
                    reconnect_count,
                )
                service.start_consuming(
                    queue_name,
                    lambda payload: self._dispatch(channel_layer, payload),
                    banner=True,
                )
            except KeyboardInterrupt:
                self.stdout.write("Interrompido pelo usuário.")
                rmq_logger.info("bridge.shutdown reason=keyboard_interrupt")
                return
            except Exception as exc:  # noqa: BLE001
                reconnect_count += 1
                sleep_for = min(backoff, 30.0)
                rmq_logger.warning(
                    "bridge.consumer_crashed err=%s:%s sleep_s=%.1f reconnect_count=%d",
                    type(exc).__name__,
                    exc,
                    sleep_for,
                    reconnect_count,
                    exc_info=True,
                )
                logger.exception("rabbit_bridge: consumer caiu, reconectando")
                time.sleep(sleep_for)
                backoff = min(backoff * 2, 30.0)
                continue
            else:
                # start_consuming só retorna em shutdown limpo
                rmq_logger.info("bridge.shutdown reason=clean_exit")
                return

    # ------------------------------------------------------------------
    # Despacho: recebe payload do Rabbit e roteia para grupos Channels
    # ------------------------------------------------------------------
    def _dispatch(self, channel_layer, payload: dict[str, Any]) -> None:
        if not isinstance(payload, dict):
            rmq_logger.warning(
                "bridge.dispatch.bad_payload class=%s repr=%r",
                type(payload).__name__,
                payload,
            )
            logger.warning("rabbit_bridge: payload não é dict, ignorando: %r", payload)
            return

        etype = payload.get("type") or "unknown"
        groups: list[str] = []

        board_id = payload.get("board_id")
        if board_id is not None:
            groups.append(f"board_{board_id}")

        user_id = payload.get("user_id")
        if user_id is not None:
            groups.append(f"user_{user_id}")

        user_ids = payload.get("user_ids") or []
        if isinstance(user_ids, (list, tuple)):
            for uid in user_ids:
                if uid is not None:
                    groups.append(f"user_{uid}")

        if payload.get("global") is True:
            groups.append("presence_global")

        if not groups:
            logger.debug(
                "rabbit_bridge: evento %s sem destinatário (nem board_id nem user_id)",
                etype,
            )
            return

        # Dedup (mesmo user aparecer em user_id + user_ids)
        seen = set()
        unique_groups = []
        for g in groups:
            if g in seen:
                continue
            seen.add(g)
            unique_groups.append(g)

        ok_count = 0
        for group in unique_groups:
            try:
                async_to_sync(channel_layer.group_send)(
                    group,
                    {"type": "broadcast", "payload": payload},
                )
                ok_count += 1
            except Exception as exc:  # noqa: BLE001
                rmq_logger.exception(
                    "bridge.group_send.fail group=%s type=%s err=%s:%s",
                    group,
                    etype,
                    type(exc).__name__,
                    exc,
                )
                logger.exception(
                    "rabbit_bridge: falha em group_send grupo=%s type=%s",
                    group,
                    etype,
                )

        rmq_logger.info(
            "bridge.dispatch.done type=%s groups_ok=%d groups_total=%d",
            etype,
            ok_count,
            len(unique_groups),
        )

    # ------------------------------------------------------------------
    def _install_signal_handlers(self):
        def _graceful(signum, frame):  # noqa: ANN001
            self.stdout.write(f"Recebido sinal {signum}, encerrando...")
            sys.exit(0)

        try:
            signal.signal(signal.SIGTERM, _graceful)
            signal.signal(signal.SIGINT, _graceful)
        except Exception:  # noqa: BLE001
            pass
