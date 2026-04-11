"""
tracktime/signals.py — pub/sub realtime para timer (Phase 3).

Quando uma TimeEntry é salva, publicamos três eventos:

1) `tracktime.me.changed` — no canal pessoal (`user_<id>`)
   Substitui o polling `/track-time/me/running.json` (35s) que alimenta
   o botão de jump no header.

2) `tracktime.changed` — no canal do board (`board_<id>`) quando a entry
   tem `board_id` setado. Substitui o polling das badges do board em
   `/track-time/boards/<id>/running/`.

3) `tracktime.activity.changed` — broadcast global (grupo `presence_global`,
   via flag `global: True`). Substitui o polling de 3s do painel "Online"
   do track-time que antes gerava ~266 req/s com 800 usuários conectados.
   Todos os navegadores conectados recebem o push; só quem estiver com
   o painel aberto é que dispara o fetch.

Os eventos são sempre disparados DEPOIS do commit (evita notificar
clientes sobre dados que acabaram em rollback).
"""

from __future__ import annotations

import logging

from django.db import transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from boards.services.pubsub_service import publish_event

from .models import TimeEntry

logger = logging.getLogger(__name__)


def _fire_events(entry: TimeEntry, *, deleted: bool = False) -> None:
    user_id = entry.user_id
    board_id = entry.board_id
    card_id = entry.card_id
    running = bool(entry.started_at and not entry.ended_at) and not deleted

    payload = {
        "entry_id": entry.id,
        "card_id": card_id,
        "board_id": board_id,
        "user_id": user_id,
        "running": running,
        "started_at": entry.started_at.isoformat() if entry.started_at else None,
        "ended_at": entry.ended_at.isoformat() if entry.ended_at else None,
    }

    def _send():
        # Canal pessoal — sempre (jump button do header, track-time modal)
        try:
            publish_event(
                "tracktime.me.changed",
                user_id=user_id,
                **payload,
            )
        except Exception:  # noqa: BLE001
            logger.debug("publish tracktime.me.changed falhou", exc_info=True)

        # Canal do board — só se a entry está vinculada a um board
        if board_id:
            try:
                publish_event(
                    "tracktime.changed",
                    board_id=board_id,
                    **payload,
                )
            except Exception:  # noqa: BLE001
                logger.debug("publish tracktime.changed falhou", exc_info=True)

        # Broadcast global — alimenta o painel "Online" do track-time
        # sem polling. Vai para `presence_global` via flag `global: True`.
        try:
            publish_event(
                "tracktime.activity.changed",
                **{"global": True, **payload},
            )
        except Exception:  # noqa: BLE001
            logger.debug(
                "publish tracktime.activity.changed falhou", exc_info=True
            )

    try:
        transaction.on_commit(_send)
    except Exception:  # noqa: BLE001
        _send()


@receiver(post_save, sender=TimeEntry)
def on_time_entry_saved(sender, instance, **kwargs):
    _fire_events(instance)


@receiver(post_delete, sender=TimeEntry)
def on_time_entry_deleted(sender, instance, **kwargs):
    _fire_events(instance, deleted=True)
