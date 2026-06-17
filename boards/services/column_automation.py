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
        return
    if a == "send_whatsapp":
        _send_whatsapp(rule, card, column, p)
        return
    # demais ações operam sobre um card específico (gatilhos de contagem não têm)
    if card is None:
        return
    if a == "assign_user":
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
        _mark_delivered(card, actor)


def _send_email(rule, card, column, p):
    to = (p.get("email") or "").strip()
    if not to:
        return
    from boards.models import Card

    custom = (p.get("message") or "").strip()
    if rule.trigger in ("count_below", "count_above"):
        count = Card.objects.filter(column=column, is_archived=False, counter_mode="").count()
        subject = f"[NossoTrello] Lista \"{column.name}\" com {count} card(s)"[:200]
        base = (
            f'A lista "{column.name}" do quadro "{column.board.name}" '
            f"está com {count} card(s)."
        )
    else:
        trig = "entrou na" if rule.trigger == "enter" else "saiu da"
        title = card.title if card else column.name
        subject = f"[NossoTrello] {title}"[:200]
        if card:
            base = (
                f'O card "{card.title}" {trig} coluna "{column.name}" '
                f'do quadro "{column.board.name}".\n\n'
                f"{(card.description or '')[:1000]}"
            )
        else:
            base = f'Atualização na coluna "{column.name}".'
    body = (custom + "\n\n" + base).strip() if custom else base
    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", None) or getattr(
        settings, "EMAIL_HOST_USER", None
    )
    send_mail(subject, body, from_email, [to], fail_silently=True)


def _whatsapp_context(rule, card, column):
    """Texto-base da notificação (sem a mensagem custom)."""
    from boards.models import Card

    if rule.trigger in ("count_below", "count_above"):
        count = Card.objects.filter(column=column, is_archived=False, counter_mode="").count()
        return (
            f'Lista "{column.name}" ({column.board.name}) está com {count} card(s).'
        )
    if card:
        trig = "entrou em" if rule.trigger == "enter" else "saiu de"
        return f'Card "{card.title}" {trig} "{column.name}" ({column.board.name}).'
    return f'Atualização na lista "{column.name}".'


def _send_whatsapp(rule, card, column, p):
    """Envia WhatsApp pela MESMA integração do resto do sistema (Evolution API),
    via boards.services.notifications.send_whatsapp. Config em settings
    (EVOLUTION_BASE_URL/API_KEY/INSTANCE) — já usada nas notificações de card.
    """
    custom = (p.get("message") or "").strip()
    base = _whatsapp_context(rule, card, column)
    message = (custom + "\n\n" + base).strip() if custom else base

    try:
        from boards.services.notifications import send_whatsapp, _safe_digits_phone
        # normaliza p/ 55 + DDD + número (Evolution exige o código do país)
        phone = _safe_digits_phone(p.get("phone") or "")
        if not phone:
            logger.warning("WhatsApp (automação): número inválido %r", p.get("phone"))
            return
        send_whatsapp(user=None, phone_digits=phone, body=message, sync=True)
    except Exception:
        logger.exception("WhatsApp (automação): falha ao enviar para %r", p.get("phone"))


def run_stale_triggers(now=None):
    """Gatilho 'card parado X dias': aplica a ação a cards que estão há >= X dias
    na lista. Chamado por cron (management command). Retorna nº de cards afetados.
    """
    from boards.models import Card, ColumnAutomation

    now = now or timezone.now()
    rules = (
        ColumnAutomation.objects.filter(trigger="stale", is_active=True)
        .select_related("column", "column__board")
    )
    affected = 0
    boards_touched = set()
    for rule in rules:
        try:
            days = int((rule.params or {}).get("days") or 0)
        except Exception:
            days = 0
        if days <= 0:
            continue
        cutoff = now - timedelta(days=days)
        cards = Card.objects.filter(
            column=rule.column, is_archived=False, counter_mode="",
            column_since__isnull=False, column_since__lte=cutoff,
        )
        for card in cards:
            try:
                _apply(rule, card, rule.column, actor=None)
                affected += 1
                boards_touched.add(rule.column.board_id)
                # re-arma o cronômetro se o card continua na mesma lista
                card.refresh_from_db(fields=["column", "column_since"])
                if card.column_id == rule.column_id:
                    card.column_since = now
                    card.save(update_fields=["column_since"])
            except Exception:
                logger.exception("stale: falha rule=%s card=%s", rule.id, card.id)

    if boards_touched:
        from boards.models import Board
        for bid in boards_touched:
            try:
                b = Board.objects.get(id=bid)
                b.version = (b.version or 0) + 1
                b.save(update_fields=["version"])
            except Exception:
                pass
    return affected


def run_count_triggers(column, actor=None):
    """Gatilhos de contagem (lista com MENOS/MAIS de X cards).

    Dispara só na transição (histerese via ColumnAutomation.armed) para não
    repetir a ação a cada card. Re-arma quando a condição deixa de valer.
    """
    from boards.models import ColumnAutomation, Card

    try:
        rules = list(
            ColumnAutomation.objects.filter(
                column=column,
                is_active=True,
                trigger__in=["count_below", "count_above"],
            )
        )
    except Exception:
        logger.exception("count trigger: falha ao buscar regras col=%s", getattr(column, "id", None))
        return
    if not rules:
        return

    count = Card.objects.filter(column=column, is_archived=False, counter_mode="").count()
    ran = False
    for rule in rules:
        try:
            x = int((rule.params or {}).get("count") or 0)
        except Exception:
            x = 0
        cond = (count < x) if rule.trigger == "count_below" else (count > x)
        if cond and rule.armed:
            try:
                _apply(rule, None, column, actor)
            except Exception:
                logger.exception("count trigger: falha rule=%s", rule.id)
            rule.armed = False
            rule.save(update_fields=["armed"])
            ran = True
        elif not cond and not rule.armed:
            rule.armed = True
            rule.save(update_fields=["armed"])

    if ran:
        try:
            board = column.board
            board.version = (board.version or 0) + 1
            board.save(update_fields=["version"])
        except Exception:
            logger.debug("count trigger: bump board falhou", exc_info=True)


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
    card.column_since = timezone.now()
    card.save(update_fields=["column", "position", "column_since"])


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

    update_fields = ["tags"]
    # cor escolhida na automação -> grava no tag_colors do card
    color = (p.get("label_color") or "").strip()
    if color:
        colors = card.tag_colors or {}
        colors[label] = color
        card.tag_colors = colors
        update_fields.append("tag_colors")

    card.save(update_fields=update_fields)


def _mark_delivered(card, actor=None):
    """Entrega COMPLETA — paridade com o botão "Entregue" manual.

    Em vez de só setar o campo, faz tudo o que a entrega manual faz:
      - marca entregue (delivered_at/delivered_by) e desliga a notificação por
        prazo/cores (due_notify=False), via mark_card_delivered;
      - registra no histórico do card (atividade do sistema);
      - notifica os seguidores por e-mail/WhatsApp (notify_delivery).
    O ícone "Entregue" aparece sozinho (é dirigido por is_delivered + o bump de
    versão do board já feito em run_for).
    """
    from boards.services.notifications import mark_card_delivered, notify_delivery
    from boards.models import CardLog

    if getattr(card, "is_delivered", False):
        return  # já entregue: não duplica log/notificação

    # 1) persiste a entrega (campos + due_notify=False + delivered_by)
    mark_card_delivered(card=card, actor=actor)

    # 2) histórico (atividade do sistema)
    try:
        who = ""
        if actor and getattr(actor, "id", None):
            prof = getattr(actor, "profile", None)
            who = (getattr(prof, "display_name", "") or "").strip() or actor.get_username()
        prefix = f"<strong>{who}</strong> " if who else ""
        CardLog.objects.create(
            card=card,
            actor=actor if (actor and getattr(actor, "id", None)) else None,
            content=f"<p>{prefix}marcou este card como <strong>Entregue</strong> (automação).</p>",
        )
    except Exception:
        logger.debug("automation: log de entrega falhou", exc_info=True)

    # 3) notifica seguidores (e-mail/WhatsApp/social), igual à entrega manual
    try:
        notify_delivery(card=card, actor=actor)
    except Exception:
        logger.debug("automation: notify_delivery falhou", exc_info=True)
