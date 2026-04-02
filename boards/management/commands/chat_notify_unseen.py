"""
Management command: notifica via WhatsApp/email mensagens de chat não lidas.

Roda a cada minuto via cron. Para cada conversa com mensagens não lidas
(>60s, não notificadas), verifica a janela de notificação do destinatário
e envia se estiver dentro do horário.

Uso:  python manage.py chat_notify_unseen
Cron: * * * * * docker compose exec -T web python manage.py chat_notify_unseen
"""

import logging
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import models
from django.utils import timezone

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Envia notificações de chat para mensagens não lidas há mais de 60s"

    def handle(self, *args, **options):
        from boards.models import ChatMessage
        from boards.services.notifications import (
            notify_chat_message,
            is_in_notification_window,
        )

        cutoff = timezone.now() - timedelta(seconds=60)

        # Mensagens: não lidas, não notificadas, com mais de 60s
        pending = (
            ChatMessage.objects
            .filter(
                is_active=True,
                seen=False,
                notified=False,
                created_at__lte=cutoff,
            )
            .select_related(
                "conversation", "conversation__user_a", "conversation__user_b",
                "sender", "sender__profile",
            )
            .order_by("created_at")
        )

        # Agrupa por (conversation, recipient) para evitar spam
        # Só notifica uma vez por conversa — a primeira msg não notificada
        notified_convs = set()
        count = 0

        for msg in pending:
            conv = msg.conversation
            # Determinar destinatário
            if msg.sender_id == conv.user_a_id:
                recipient = conv.user_b
            else:
                recipient = conv.user_a

            conv_recipient_key = (conv.id, recipient.id)
            if conv_recipient_key in notified_convs:
                # Já notificou esta conversa, só marca como notificada
                msg.notified = True
                msg.save(update_fields=["notified"])
                continue

            prof = getattr(recipient, "profile", None)
            if not prof:
                msg.notified = True
                msg.save(update_fields=["notified"])
                continue

            if not is_in_notification_window(prof):
                # Fora da janela — não marca como notificada, tenta de novo depois
                continue

            # Envia notificação
            preview = (msg.text or "").strip()[:60]
            if not preview:
                if msg.gif_url:
                    preview = "GIF 🎞️"
                elif msg.sticker_url:
                    preview = "Figurinha 🩷"

            try:
                notify_chat_message(
                    recipient=recipient,
                    sender=msg.sender,
                    message_preview=preview,
                )
                count += 1
            except Exception:
                logger.exception(
                    "chat_notify_unseen: falha ao notificar user_id=%s msg_id=%s",
                    recipient.id, msg.id,
                )

            # Marca todas as mensagens pendentes desta conversa como notificadas
            ChatMessage.objects.filter(
                conversation=conv,
                seen=False,
                notified=False,
                is_active=True,
            ).exclude(sender=recipient).update(notified=True)

            notified_convs.add(conv_recipient_key)

        if count:
            self.stdout.write(f"Notificações enviadas: {count}")
