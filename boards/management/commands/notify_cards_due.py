# boards/management/commands/notify_cards_due.py

from __future__ import annotations

import datetime
import logging
import time
from collections import defaultdict

from django.core.management.base import BaseCommand
from django.utils import timezone

from boards.models import Card, CardNotificationLog
from boards.services.notifications import (
    get_board_recipients_for_card,
    build_card_snapshot,
    format_card_message,
    send_whatsapp,
    send_email_notification,
    _get_or_create_profile,
    _safe_digits_phone,
    is_in_notification_window,
)

logger = logging.getLogger(__name__)

# Intervalo (em segundos) entre cada par mensagem+link para o mesmo número
DELAY_BETWEEN_MESSAGES_S = 60
# Pequeno intervalo entre a mensagem e o link dela (garante ordem)
DELAY_MSG_LINK_S = 3


class Command(BaseCommand):
    help = "Dispara notificações de cards (Data Aviso / véspera / vencimento) - rodar às 08:00."

    def add_arguments(self, parser):
        parser.add_argument(
            "--kind",
            required=True,
            choices=["warn", "warn_minus_1", "due_minus_1", "due"],
            help="Tipo de disparo.",
        )
        parser.add_argument(
            "--delay",
            type=int,
            default=DELAY_BETWEEN_MESSAGES_S,
            help="Segundos entre cada mensagem para o mesmo número (padrão: 60).",
        )

    def handle(self, *args, **opts):
        kind = opts["kind"]
        delay = opts["delay"]
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

        # ── Fase 1: coletar todas as notificações pendentes ──
        # phone_queue: { phone_digits: [(user, message, link, subject)] }
        phone_queue: dict[str, list[tuple]] = defaultdict(list)
        email_queue: list[tuple] = []
        sent = 0
        skipped = 0

        for card in qs.iterator():
            recipients = get_board_recipients_for_card(card=card)
            snap = build_card_snapshot(card=card)
            msg = format_card_message(title_prefix=title, snap=snap)
            subject = f"{title}: {snap.title}"
            link = snap.card_url

            for u in recipients:
                # idempotência por usuário/card/kind/dia
                _, created = CardNotificationLog.objects.get_or_create(
                    card=card,
                    user=u,
                    kind=kind,
                    run_date=today,
                )
                if not created:
                    skipped += 1
                    continue

                prof = _get_or_create_profile(u)

                # Respeita janela de notificação do usuário
                if not is_in_notification_window(prof):
                    skipped += 1
                    continue

                # WhatsApp — enfileira por telefone
                if getattr(prof, "notify_whatsapp", False):
                    phone_digits = _safe_digits_phone(getattr(prof, "telefone", ""))
                    if phone_digits:
                        phone_queue[phone_digits].append((u, msg, link))

                # Email — dispara em background (não tem problema de ordem)
                if getattr(prof, "notify_email", False):
                    to_email = (getattr(u, "email", "") or "").strip()
                    if to_email:
                        body = f"{msg}\n\nLink: {link}\n"
                        send_email_notification(to_email=to_email, subject=subject, body=body)

                sent += 1

        # ── Fase 2: enviar WhatsApp com throttle por número ──
        total_phones = len(phone_queue)
        total_wa = sum(len(v) for v in phone_queue.values())
        self.stdout.write(f"WhatsApp: {total_wa} mensagens para {total_phones} números")

        for phone_digits, items in phone_queue.items():
            for i, (user, msg, link) in enumerate(items):
                # Envia a mensagem (síncrono — garante ordem)
                send_whatsapp(user=user, phone_digits=phone_digits, body=msg, sync=True)
                # Pequena pausa para garantir que o link chegue depois
                time.sleep(DELAY_MSG_LINK_S)
                # Envia o link
                send_whatsapp(user=user, phone_digits=phone_digits, body=link, sync=True)

                # Aguarda antes da próxima mensagem (exceto a última)
                if i < len(items) - 1:
                    self.stdout.write(f"  {phone_digits}: {i+1}/{len(items)} enviado, aguardando {delay}s...")
                    time.sleep(delay)

            self.stdout.write(f"  {phone_digits}: {len(items)}/{len(items)} concluído ✓")

        self.stdout.write(self.style.SUCCESS(f"done kind={kind} sent={sent} skipped={skipped}"))
