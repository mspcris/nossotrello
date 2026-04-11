"""
WebSocket consumers — ponte entre o Channels (Redis channel layer) e o browser.

Fluxo completo de um evento:

    [view] board.version += 1 --post_save--> signal
      -> publish_event("board.invalidated", board_id=X, version=N)
      -> RabbitMQ exchange "nossotrello"
      -> rabbit_bridge (processo separado) consome
      -> group_send("board_<X>", {"type": "broadcast", "payload": {...}})
      -> BoardConsumer.broadcast  envia pro socket do browser

O consumer em si é burro: só valida acesso, entra no grupo, e retransmite
o que chega. Toda a lógica de quando publicar mora em signals/views.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------
# BoardConsumer: um grupo por board (`board_<id>`).
# ----------------------------------------------------------------------
class BoardConsumer(AsyncJsonWebsocketConsumer):
    """
    Canal WS para um board específico. Só entra no grupo se o usuário
    autenticado tiver membership (ou for superuser).

    URL: ws://.../ws/board/<board_id>/
    """

    group_name: str | None = None

    async def connect(self):
        user = self.scope.get("user")
        if user is None or not user.is_authenticated:
            await self.close(code=4401)  # custom code: não autenticado
            return

        try:
            board_id = int(self.scope["url_route"]["kwargs"]["board_id"])
        except (KeyError, ValueError, TypeError):
            await self.close(code=4400)  # custom code: id inválido
            return

        allowed = await self._user_can_view(user.id, board_id)
        if not allowed:
            await self.close(code=4403)  # custom code: sem permissão
            return

        self.group_name = f"board_{board_id}"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

        # Envia hello para o cliente confirmar handshake
        await self.send_json(
            {"type": "hello", "board_id": board_id, "group": self.group_name}
        )

    async def disconnect(self, code):  # noqa: ANN001
        if self.group_name:
            try:
                await self.channel_layer.group_discard(
                    self.group_name, self.channel_name
                )
            except Exception:  # noqa: BLE001
                logger.debug("disconnect: group_discard falhou", exc_info=True)

    async def receive_json(self, content, **kwargs):
        """
        O cliente pode mandar ping para manter conexão. Nada além disso.
        """
        mtype = (content or {}).get("type")
        if mtype == "ping":
            await self.send_json({"type": "pong"})

    # ------------------------------------------------------------------
    # Handler para mensagens do channel layer (group_send)
    # ------------------------------------------------------------------
    async def broadcast(self, event: dict[str, Any]):
        """
        Recebe do channel layer e repassa payload ao cliente.
        O bridge chama group_send(..., {"type": "broadcast", "payload": {...}}).
        """
        payload = event.get("payload") or {}
        try:
            await self.send_json(payload)
        except Exception:  # noqa: BLE001
            logger.debug("broadcast: falha enviando ao socket", exc_info=True)

    # ------------------------------------------------------------------
    # DB access
    # ------------------------------------------------------------------
    @database_sync_to_async
    def _user_can_view(self, user_id: int, board_id: int) -> bool:
        try:
            from .models import Board  # import local para evitar ciclo
        except Exception:  # noqa: BLE001
            return False

        try:
            board = Board.objects.get(id=board_id)
        except Board.DoesNotExist:
            return False

        # preferir o método canônico do modelo, se existir
        check = getattr(board, "user_can_view", None)
        if callable(check):
            try:
                from django.contrib.auth import get_user_model

                User = get_user_model()
                user = User.objects.get(id=user_id)
                return bool(check(user))
            except Exception:  # noqa: BLE001
                return False

        # fallback: membership direta
        return board.memberships.filter(user_id=user_id).exists()


# ----------------------------------------------------------------------
# UserConsumer: canal pessoal do usuário (`user_<id>`).
# Usado para eventos que não pertencem a um board específico:
# notificações, chat badge, track-time do próprio usuário, etc.
# ----------------------------------------------------------------------
class UserConsumer(AsyncJsonWebsocketConsumer):
    """
    URL: ws://.../ws/me/
    Entra automaticamente no grupo `user_<id>` do usuário autenticado e
    também no grupo `presence_global` (broadcast para todos os logados —
    usado por eventos como `tracktime.activity.changed` que alimentam
    o painel "Online" sem polling).
    """

    PRESENCE_GROUP = "presence_global"

    group_name: str | None = None

    async def connect(self):
        user = self.scope.get("user")
        if user is None or not user.is_authenticated:
            await self.close(code=4401)
            return

        self.group_name = f"user_{user.id}"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.channel_layer.group_add(self.PRESENCE_GROUP, self.channel_name)
        await self.accept()
        await self.send_json({"type": "hello", "group": self.group_name})

    async def disconnect(self, code):  # noqa: ANN001
        if self.group_name:
            try:
                await self.channel_layer.group_discard(
                    self.group_name, self.channel_name
                )
            except Exception:  # noqa: BLE001
                logger.debug("disconnect: group_discard falhou", exc_info=True)
            try:
                await self.channel_layer.group_discard(
                    self.PRESENCE_GROUP, self.channel_name
                )
            except Exception:  # noqa: BLE001
                logger.debug(
                    "disconnect: group_discard presence falhou", exc_info=True
                )

    async def receive_json(self, content, **kwargs):
        if (content or {}).get("type") == "ping":
            await self.send_json({"type": "pong"})

    async def broadcast(self, event: dict[str, Any]):
        payload = event.get("payload") or {}
        try:
            await self.send_json(payload)
        except Exception:  # noqa: BLE001
            logger.debug("broadcast: falha enviando ao socket", exc_info=True)
