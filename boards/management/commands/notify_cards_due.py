# boards/management/commands/notify_cards_due.py

from __future__ import annotations

import datetime
import logging

from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from boards.models import Card, CardNotificationLog
from boards.services.notifications import (
    get_board_recipients_for_card,
    build_card_snapshot,
    format_card_message,
    notify_users_for_card,
)

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Dispara notificações de cards (Data Aviso / véspera / vencimento) - rodar às 08:00."

    def add_arguments(self, parser):
        parser.add_argument(
            "--kind",
            required=True,
            choices=["warn", "warn_minus_1", "due_minus_1", "due"],
            help="Tipo de disparo.",
        )

    def handle(self, *args, **opts):
        kind = opts["kind"]
        today = timezone.localdate()

        if kind == "warn":
            qs = Card.objects.filter(due_notify=True, due_warn_date=today)
            title = "🔔 Data de Aviso do Card (hoje)"
        elif kind == "warn_minus_1":
            qs = Card.objects.filter(due_notify=True, due_warn_date=today + datetime.timedelta(days=1))
            title = "🔔 Véspera da Data de Aviso do Card"
        elif kind == "due_minus_1":
            qs = Card.objects.filter(due_notify=True, due_date=today + datetime.timedelta(days=1))
            title = "⏳ Véspera do Vencimento do Card"
        else:  # due
            qs = Card.objects.filter(due_notify=True, due_date=today)
            title = "⛔ Vencimento do Card (hoje)"

        # Só cards vivos e boards vivos
        qs = qs.filter(
            is_deleted=False,
            is_archived=False,
            column__is_deleted=False,
            column__board__is_deleted=False,
            column__board__is_archived=False,
        ).select_related("column", "column__board")

        sent = 0
        skipped = 0

        for card in qs.iterator():
            recipients = get_board_recipients_for_card(card=card)
            snap = build_card_snapshot(card=card)

            msg = format_card_message(
                title_prefix=title,
                snap=snap,
            )

            for u in recipients:
                # idempotência por usuário/card/kind/dia
                obj, created = CardNotificationLog.objects.get_or_create(
                    card=card,
                    user=u,
                    kind=kind,
                    run_date=today,
                )
                if not created:
                    skipped += 1
                    continue

                notify_users_for_card(
                    card=card,
                    recipients=[u],
                    subject=f"{title}: {snap.title}",
                    message=msg,
                    include_link_as_second_whatsapp_message=True,
                )
                sent += 1

        self.stdout.write(self.style.SUCCESS(f"done kind={kind} sent={sent} skipped={skipped}"))
