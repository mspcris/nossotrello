# boards/services/column_autosort.py
"""Auto-ordenação agendada da coluna (Trello-like: todo dia / toda semana)."""
import logging
from datetime import date as _date

logger = logging.getLogger(__name__)


def _key_func(field):
    if field == "due":
        return lambda c: (c.due_date is None, c.due_date or _date.max)
    if field == "start":
        return lambda c: (c.start_date is None, c.start_date or _date.max)
    if field == "title":
        return lambda c: (c.title or "").strip().lower()
    # created -> sem created_at no Card; usa o id como ordem de criação
    return lambda c: c.id


def apply_autosort(column):
    """Reordena os cards ativos da coluna conforme o critério e grava position.
    Retorna o nº de cards reordenados."""
    from boards.models import Card

    cards = list(Card.objects.filter(column=column))  # manager ativo (sem deleted/archived)
    if not cards:
        return 0

    # cards contadores ficam fixos no topo (preservam a ordem atual); só os reais são ordenados
    counters = sorted([c for c in cards if c.counter_mode], key=lambda c: int(c.position or 0))
    reais = [c for c in cards if not c.counter_mode]
    reais.sort(key=_key_func(column.autosort_field), reverse=(column.autosort_dir == "desc"))
    ordered = counters + reais

    changed = 0
    for i, c in enumerate(ordered):
        if int(c.position or 0) != i:
            c.position = i
            c.save(update_fields=["position"])
            changed += 1

    # bump na versão do board -> realtime
    try:
        b = column.board
        b.version = (b.version or 0) + 1
        b.save(update_fields=["version"])
    except Exception:
        logger.debug("autosort: bump board falhou", exc_info=True)
    return changed


def is_due(column, now):
    """True se a coluna deve ser auto-ordenada agora.

    `now` é um datetime local (timezone.localtime()). Respeita o horário
    configurado (autosort_hour:autosort_minute) e roda só 1x por dia.
    """
    freq = column.autosort_freq
    if freq not in ("daily", "weekly"):
        return False
    today = now.date()
    if column.autosort_last_run == today:
        return False
    # o horário agendado já chegou hoje?
    sched = (int(column.autosort_hour or 0), int(column.autosort_minute or 0))
    if (now.hour, now.minute) < sched:
        return False
    if freq == "weekly" and today.weekday() != int(column.autosort_weekday or 0):
        return False
    return True
