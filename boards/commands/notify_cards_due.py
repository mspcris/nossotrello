from __future__ import annotations

import logging
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from boards.models import Board, Card
from tracktime.services.notifications import notify_card_deadline

logger = logging.getLogger(__name__)


def _local_today():
    return timezone.localdate()


def _local_hour():
    return timezone.localtime(timezone.now()).hour


def _get_board_recipients(board):
    """
    Estratégia simples e previsível:
    - se board tem memberships, notifica todos
    - senão, notifica created_by (fallback legado)
    """
    memberships = getattr(board, "memberships", None)
    if memberships is not None and memberships.exists():
        return [m.user for m in memberships.select_related("user").all() if m.user]
    created_by = getattr(board, "created_by", None)
    return [created_by] if created_by else []


class Command(BaseCommand):
    help = "Notifica avisos/vencimentos de cards (08:00)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Roda mesmo fora das 08:00 (para teste/manual).",
        )
        parser.add_argument(
            "--board-id",
            type=int,
            default=0,
            help="Filtra por um board específico (debug).",
        )

    def handle(self, *args, **opts):
        force = bool(opts.get("force"))
        board_id = int(opts.get("board_id") or 0)

        if not force and _local_hour() != 8:
            self.stdout.write("Skip: este command só roda às 08:00 (use --force para teste).")
            return

        today = _local_today()
        tomorrow = today + timedelta(days=1)

        qs = Card.objects.filter(is_deleted=False).select_related("column", "column__board")
        if board_id:
            qs = qs.filter(column__board_id=board_id)

        sent = 0

        for card in qs.iterator():
            board = getattr(getattr(card, "column", None), "board", None)
            if not board:
                continue

            warn_date = getattr(card, "due_warn_date", None)
            due_date = getattr(card, "due_date", None)

            # ---- WARN (hoje) ----
            if warn_date and warn_date == today and getattr(card, "warn_notified_on", None) != today:
                recipients = _get_board_recipients(board)
                for u in recipients:
                    notify_card_deadline(user=u, card=card, kind="warn_today")
                    sent += 1
                Card.objects.filter(id=card.id).update(warn_notified_on=today)

            # ---- WARN (amanhã) ----
            if warn_date and warn_date == tomorrow and getattr(card, "warn_minus_1_notified_on", None) != today:
                recipients = _get_board_recipients(board)
                for u in recipients:
                    notify_card_deadline(user=u, card=card, kind="warn_minus_1")
                    sent += 1
                # marca "hoje" como o dia em que enviou o aviso de véspera
                Card.objects.filter(id=card.id).update(warn_minus_1_notified_on=today)

            # ---- DUE (amanhã) ----
            if due_date and due_date == tomorrow and getattr(card, "due_minus_1_notified_on", None) != today:
                recipients = _get_board_recipients(board)
                for u in recipients:
                    notify_card_deadline(user=u, card=card, kind="due_minus_1")
                    sent += 1
                Card.objects.filter(id=card.id).update(due_minus_1_notified_on=today)

            # ---- DUE (hoje) ----
            if due_date and due_date == today and getattr(card, "due_notified_on", None) != today:
                recipients = _get_board_recipients(board)
                for u in recipients:
                    notify_card_deadline(user=u, card=card, kind="due_today")
                    sent += 1
                Card.objects.filter(id=card.id).update(due_notified_on=today)

        self.stdout.write(f"OK: notificações disparadas (eventos individuais) = {sent}")
