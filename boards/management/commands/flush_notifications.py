# boards/management/commands/flush_notifications.py
"""
Consolida e envia notificações de atividade em cards.

Roda a cada 5 minutos via cron. Agrupa eventos por (card, recipient)
e envia UMA mensagem por card com todas as atividades recentes.

Exemplo de mensagem consolidada:
    📋 *Tarefas Lincoln* → Sprint
    *Card:* [CRM] - CRIAR API PARA INSERT DE CRM

    ✏️ 3 atividades por Lincoln Menezes:
    • moveu o card para Sprint
    • adicionou comentário
    • alterou descrição

    🔗 https://tarefas.camim.com.br/board/71/?card=1081
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from boards.models import NotificationBuffer, Card
from boards.services.notifications import (
    build_card_snapshot,
    send_whatsapp,
    send_email_notification,
    _get_or_create_profile,
    _safe_digits_phone,
    _wa_safe,
    _wa_bold,
    is_in_notification_window,
)

logger = logging.getLogger(__name__)


def _build_digest(card: Card, events: list[dict]) -> tuple[str, str]:
    """
    Monta mensagem consolidada para WhatsApp e subject para email.
    events: [{"actor_name": str, "event_summary": str, "created_at": datetime}]
    Retorna (mensagem_wa, subject_email).
    """
    snap = build_card_snapshot(card=card)

    board = _wa_safe(snap.board_name)
    col = _wa_safe(snap.column_name)
    title = _wa_safe(snap.title)

    # Agrupar por actor
    by_actor: dict[str, list[str]] = defaultdict(list)
    for ev in events:
        actor = ev["actor_name"] or "Sistema"
        summary = ev["event_summary"]
        # Limpar prefixos comuns do log HTML já stripado
        summary = summary.strip()
        if summary:
            by_actor[actor].append(summary)

    # Montar mensagem
    n_total = len(events)
    lines = [
        f"📋 {_wa_bold(board)} → {col}",
        f"{_wa_bold('Card:')} {title}",
        "",
    ]

    for actor, summaries in by_actor.items():
        n = len(summaries)
        actor_safe = _wa_safe(actor)
        if n == 1:
            lines.append(f"✏️ {actor_safe}:")
        else:
            lines.append(f"✏️ {n} atividades por {actor_safe}:")
        for s in summaries[-8:]:  # max 8 por ator para não ficar enorme
            short = _wa_safe(s[:120]) if len(s) > 120 else _wa_safe(s)
            lines.append(f"  • {short}")
        if n > 8:
            lines.append(f"  _… e mais {n - 8}_")
        lines.append("")

    lines.append(f"🔗 {snap.card_url}")

    msg_wa = "\n".join(lines).strip()
    subject = f"📋 {snap.board_name} — {snap.title} ({n_total} atividade{'s' if n_total > 1 else ''})"

    return msg_wa, subject


class Command(BaseCommand):
    help = "Consolida e envia notificações de atividade (rodar a cada 5 min)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--min-age",
            type=int,
            default=5,
            help="Idade mínima em minutos dos eventos antes de enviar (padrão: 5).",
        )

    def handle(self, *args, **opts):
        min_age = opts["min_age"]
        cutoff = timezone.now() - timedelta(minutes=min_age)

        # Busca eventos não enviados com pelo menos min_age minutos
        pending = (
            NotificationBuffer.objects
            .filter(sent=False, created_at__lte=cutoff)
            .select_related("card", "card__column", "card__column__board", "recipient")
            .order_by("created_at")
        )

        if not pending.exists():
            self.stdout.write("Nenhuma notificação pendente.")
            return

        # Agrupar por (card_id, recipient_id)
        groups: dict[tuple[int, int], list] = defaultdict(list)
        buffer_ids_by_key: dict[tuple[int, int], list] = defaultdict(list)

        for buf in pending:
            key = (buf.card_id, buf.recipient_id)
            groups[key].append({
                "actor_name": buf.actor_name,
                "event_summary": buf.event_summary,
                "created_at": buf.created_at,
            })
            buffer_ids_by_key[key].append(buf.id)

        sent_count = 0
        sent_ids = []
        deferred_count = 0

        for (card_id, recipient_id), events in groups.items():
            try:
                card = Card.objects.select_related("column", "column__board").get(id=card_id)
            except Card.DoesNotExist:
                # Card apagado → marca como enviado para limpar fila
                sent_ids.extend(buffer_ids_by_key[(card_id, recipient_id)])
                continue

            # Pegar recipient
            from django.contrib.auth import get_user_model
            User = get_user_model()
            try:
                recipient = User.objects.select_related("profile").get(id=recipient_id)
            except User.DoesNotExist:
                sent_ids.extend(buffer_ids_by_key[(card_id, recipient_id)])
                continue

            # Card entregue → não notifica
            if getattr(card, "is_delivered", False):
                sent_ids.extend(buffer_ids_by_key[(card_id, recipient_id)])
                continue

            prof = _get_or_create_profile(recipient)

            # Verifica janela de notificação do usuário
            if not is_in_notification_window(prof):
                deferred_count += 1
                continue  # deixa no buffer para a próxima janela

            msg_wa, subject = _build_digest(card, events)

            # WhatsApp
            if getattr(prof, "notify_whatsapp", False):
                phone = _safe_digits_phone(getattr(prof, "telefone", ""))
                if phone:
                    send_whatsapp(user=recipient, phone_digits=phone, body=msg_wa)

            # Email
            if getattr(prof, "notify_email", False):
                email = (getattr(recipient, "email", "") or "").strip()
                if email:
                    send_email_notification(to_email=email, subject=subject, body=msg_wa)

            sent_ids.extend(buffer_ids_by_key[(card_id, recipient_id)])
            sent_count += 1

        # Marcar como enviados apenas os que foram de fato processados
        if sent_ids:
            NotificationBuffer.objects.filter(id__in=sent_ids).update(sent=True)

        msg = f"Enviadas {sent_count} notificações consolidadas ({len(sent_ids)} eventos)."
        if deferred_count:
            msg += f" {deferred_count} adiadas (fora da janela do usuário)."
        self.stdout.write(self.style.SUCCESS(msg))
