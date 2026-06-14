# boards/services/column_automation.py
"""
Automação da coluna (estilo Trello, sem construtor de regras).

Gatilhos: card ENTRA / SAI da lista -> executa ação.
Ações: disparar e-mail, mover para outra coluna, definir data (+N dias),
adicionar etiqueta, marcar como entregue.

Chamado de move_card (enter/leave) e add_card (enter). Nunca deve quebrar o
fluxo principal: tudo encapsulado em try/except.
"""
import logging
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

logger = logging.getLogger(__name__)


def run_for(card, trigger, column, actor=None):
    """Roda as automações ativas da coluna para o gatilho ('enter'/'leave')."""
    from boards.models import ColumnAutomation

    try:
        rules = list(
            ColumnAutomation.objects.filter(
                column=column, trigger=trigger, is_active=True
            )
        )
    except Exception:
        logger.exception("automation: falha ao buscar regras col=%s", getattr(column, "id", None))
        return

    if not rules:
        return

    ran = False
    for rule in rules:
        try:
            _apply(rule, card, column, actor)
            ran = True
        except Exception:
            logger.exception("automation: falha rule=%s card=%s", rule.id, getattr(card, "id", None))

    # mudou algo no card/colunas -> bump na versão do board (realtime)
    if ran:
        try:
            board = column.board
            board.version = (board.version or 0) + 1
            board.save(update_fields=["version"])
        except Exception:
            logger.debug("automation: bump board falhou", exc_info=True)


def _apply(rule, card, column, actor):
    p = rule.params or {}
    a = rule.action
    if a == "send_email":
        _send_email(rule, card, column, p)
    elif a == "assign_user":
        _assign_user(card, p)
    elif a == "move_to":
        _move_to(card, p)
    elif a == "copy_to":
        _copy_to(card, p)
    elif a == "set_due":
        _set_due(card, p)
    elif a == "set_start":
        _set_start(card, p)
    elif a == "add_label":
        _add_label(card, p)
    elif a == "mark_delivered":
        _mark_delivered(card)


def _send_email(rule, card, column, p):
    to = (p.get("email") or "").strip()
    if not to:
        return
    trig = "entrou na" if rule.trigger == "enter" else "saiu da"
    subject = f"[NossoTrello] {card.title}"[:200]
    body = (
        f'O card "{card.title}" {trig} coluna "{column.name}" '
        f'do quadro "{column.board.name}".\n\n'
        f"{(card.description or '')[:1000]}"
    )
    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", None) or getattr(
        settings, "EMAIL_HOST_USER", None
    )
    send_mail(subject, body, from_email, [to], fail_silently=True)


def _move_to(card, p):
    from boards.models import Card, Column

    tid = p.get("target_column_id")
    if not tid:
        return
    target = Column.objects.filter(id=tid, is_deleted=False).first()
    if not target or target.id == card.column_id:
        return
    last = Card.objects.filter(column=target).count()
    card.column = target
    card.position = last
    card.save(update_fields=["column", "position"])


def _copy_to(card, p):
    from boards.models import Card, Column

    tid = p.get("target_column_id")
    target = Column.objects.filter(id=tid, is_deleted=False).first()
    if not target:
        return
    last = Card.objects.filter(column=target).count()
    Card.all_objects.create(
        column=target,
        title=card.title,
        description=card.description or "",
        tags=card.tags or "",
        due_date=card.due_date,
        start_date=card.start_date,
        position=last,
        created_by=card.created_by,
    )


def _set_due(card, p):
    try:
        days = int(p.get("days") or 0)
    except Exception:
        days = 0
    card.due_date = (timezone.now() + timedelta(days=days)).date()
    card.save(update_fields=["due_date"])


def _set_start(card, p):
    try:
        days = int(p.get("days") or 0)
    except Exception:
        days = 0
    card.start_date = (timezone.now() + timedelta(days=days)).date()
    card.save(update_fields=["start_date"])


def _assign_user(card, p):
    """Marca uma pessoa criando um acompanhamento (CardFollow)."""
    from boards.models import CardFollow

    uid = p.get("user_id")
    if not uid:
        return
    try:
        CardFollow.objects.get_or_create(card_id=card.id, user_id=uid)
    except Exception:
        logger.debug("assign_user: CardFollow falhou", exc_info=True)


def _add_label(card, p):
    label = (p.get("label") or "").strip()
    if not label:
        return
    parts = [t.strip() for t in (card.tags or "").split(",") if t.strip()]
    if label not in parts:
        parts.append(label)
    card.tags = ", ".join(parts)[:255]
    card.save(update_fields=["tags"])


def _mark_delivered(card):
    card.is_delivered = True
    card.delivered_at = timezone.now()
    card.save(update_fields=["is_delivered", "delivered_at"])
