"""EMAIL_BACKEND que enfileira: todo send_mail/EmailMessage.send do projeto sai
da requisição e ganha tentativas com espera crescente (boards.tasks.deliver_email).

O envio real usa settings.QUEUED_EMAIL_REAL_BACKEND (o backend que estava
configurado antes). Conexões explícitas (a conta SMTP da parte social, via
get_connection) não passam por aqui e continuam como eram.
"""
from __future__ import annotations

import base64
import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives, get_connection
from django.core.mail.backends.base import BaseEmailBackend

logger = logging.getLogger(__name__)


def _serialize(msg):
    """EmailMessage -> dict JSON. None se houver anexo que não dá para serializar."""
    attachments = []
    for att in getattr(msg, "attachments", None) or []:
        if not isinstance(att, (tuple, list)) or len(att) != 3:
            return None  # MIMEBase pronto: manda direto
        filename, content, mimetype = att
        if isinstance(content, str):
            content = content.encode("utf-8")
        if not isinstance(content, (bytes, bytearray)):
            return None
        attachments.append([filename, base64.b64encode(bytes(content)).decode("ascii"), mimetype])
    alternatives = [[a[0], a[1]] for a in (getattr(msg, "alternatives", None) or [])]
    return {
        "subject": str(msg.subject or ""),
        "body": str(msg.body or ""),
        "from_email": msg.from_email,
        "to": list(msg.to or []),
        "cc": list(msg.cc or []),
        "bcc": list(msg.bcc or []),
        "reply_to": list(msg.reply_to or []),
        "headers": {str(k): str(v) for k, v in (msg.extra_headers or {}).items()},
        "content_subtype": getattr(msg, "content_subtype", "plain"),
        "alternatives": alternatives,
        "attachments": attachments,
    }


def _real_connection():
    backend = getattr(settings, "QUEUED_EMAIL_REAL_BACKEND", None) or "django.core.mail.backends.smtp.EmailBackend"
    return get_connection(backend=backend, fail_silently=False)


def deliver_now(payload: dict) -> int:
    """Envia de verdade (chamado pelo worker, ou direto quando a fila está fora)."""
    msg = EmailMultiAlternatives(
        subject=payload.get("subject", ""),
        body=payload.get("body", ""),
        from_email=payload.get("from_email"),
        to=payload.get("to") or [],
        cc=payload.get("cc") or [],
        bcc=payload.get("bcc") or [],
        reply_to=payload.get("reply_to") or [],
        headers=payload.get("headers") or {},
        connection=_real_connection(),
    )
    msg.content_subtype = payload.get("content_subtype") or "plain"
    for content, mimetype in payload.get("alternatives") or []:
        msg.attach_alternative(content, mimetype)
    for filename, b64, mimetype in payload.get("attachments") or []:
        msg.attach(filename, base64.b64decode(b64), mimetype)
    return msg.send(fail_silently=False)


class QueuedEmailBackend(BaseEmailBackend):
    def send_messages(self, email_messages):
        from boards.services.jobs import enqueue
        from boards.tasks import deliver_email

        sent = 0
        for msg in email_messages or []:
            if not msg.recipients():
                continue
            payload = _serialize(msg)
            try:
                if payload is None:
                    conn = _real_connection()
                    sent += conn.send_messages([msg]) or 0
                    continue
                # broker fora: envia na hora, como sempre foi
                enqueue(deliver_email, payload, fallback=lambda p=payload: deliver_now(p), mode="sync")
                sent += 1
            except Exception:
                if not self.fail_silently:
                    raise
                logger.exception("queued_email: falha ao enfileirar/enviar")
        return sent
