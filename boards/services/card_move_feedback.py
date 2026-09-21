"""Aviso ao usuário quando um mover-card em fila falha de vez.

1. Evento `card.move.failed` só para ele (WebSocket do usuário): a tela mostra a
   mensagem e ressincroniza o quadro, devolvendo o card ao lugar real.
2. E-mail com as tentativas e o erro de cada uma.
"""
from __future__ import annotations

import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail

logger = logging.getLogger(__name__)


def notify_move_failed(*, op_id, card_id, user_id, attempts, reason: str = "") -> None:
    from boards.models import Card
    from boards.services.pubsub_service import publish_event

    info = (
        Card.all_objects.filter(id=card_id)
        .values("title", "column__name", "column__board_id", "column__board__name")
        .first()
    ) or {}
    title = (info.get("title") or f"#{card_id}").strip()
    board_id = info.get("column__board_id")
    n = len(attempts or [])

    if reason:
        message = f"Não foi possível mover o card “{title}”: {reason}"
    else:
        message = f"Não foi possível mover o card “{title}”. Tentamos {n} vez{'es' if n != 1 else ''} e não deu certo — ele voltou ao lugar original."

    try:
        publish_event(
            "card.move.failed",
            user_id=user_id,          # só o autor do movimento recebe
            op_id=op_id,
            card_id=card_id,
            card_title=title,
            src_board_id=board_id,    # de propósito NÃO é `board_id`: a ponte mandaria pro quadro inteiro
            attempts=n,
            message=message,
        )
    except Exception:
        logger.exception("move.failed: não consegui publicar o evento (op=%s)", op_id)

    try:
        user = get_user_model().objects.filter(pk=user_id).first()
        email = (getattr(user, "email", "") or "").strip()
        if not email:
            return
        base = (getattr(settings, "SITE_URL", "") or "https://tarefas.camim.com.br").rstrip("/")
        link = f"{base}/board/{board_id}/?card={card_id}" if board_id else base
        lines = [
            f"Não conseguimos gravar a movimentação do card “{title}”.",
            "",
            f"Quadro: {info.get('column__board__name') or '-'}",
            f"Coluna atual (onde o card continua): {info.get('column__name') or '-'}",
            "",
            "Tentativas:",
        ]
        for a in attempts or []:
            lines.append(f"  {a.get('n')}ª — {a.get('at')} — {a.get('error') or 'erro não informado'}")
        lines += [
            "",
            "O card permanece onde estava. Você pode tentar mover de novo:",
            link,
        ]
        send_mail(
            f"Não foi possível mover o card “{title}”",
            "\n".join(lines),
            settings.DEFAULT_FROM_EMAIL,
            [email],
            fail_silently=True,
        )
    except Exception:
        logger.exception("move.failed: não consegui enviar o e-mail (op=%s)", op_id)
