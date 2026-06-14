"""
Cards contadores: um card especial que mostra um número grande, calculado ao
vivo sobre os cards REAIS da mesma coluna (cards contadores não contam entre si).

Modos:
- total          : total de cards reais na lista
- done_recent    : entregues nos últimos X dias (counter_days)
- delivered      : entregues (total)
- not_delivered  : não entregues
- overdue        : prazo vencido (e não entregue)
- stale          : parados há X+ dias na lista (column_since)
"""
from datetime import timedelta

from django.utils import timezone


def compute_counter_value(card):
    """Retorna o número que o card contador deve exibir."""
    from boards.models import Card

    mode = card.counter_mode
    if not mode:
        return None

    # base: cards REAIS, ativos, da mesma coluna (exclui contadores e arquivados)
    base = Card.objects.filter(column_id=card.column_id, is_archived=False, counter_mode="")
    try:
        days = int(card.counter_days or 0)
    except Exception:
        days = 0

    if mode == "total":
        return base.count()
    if mode == "delivered":
        return base.filter(is_delivered=True).count()
    if mode == "not_delivered":
        return base.filter(is_delivered=False).count()
    if mode == "done_recent":
        cutoff = timezone.now() - timedelta(days=days)
        return base.filter(is_delivered=True, delivered_at__gte=cutoff).count()
    if mode == "overdue":
        today = timezone.localdate()
        return base.filter(is_delivered=False, due_date__isnull=False, due_date__lt=today).count()
    if mode == "stale":
        cutoff = timezone.now() - timedelta(days=days)
        return base.filter(column_since__isnull=False, column_since__lte=cutoff).count()
    return 0


def default_title_for(mode, days):
    labels = {
        "total": "Total",
        "done_recent": f"Entregues ({days} dias)",
        "delivered": "Entregues",
        "not_delivered": "Não entregues",
        "overdue": "Prazo vencido",
        "stale": f"Parados {days}+ dias",
    }
    return labels.get(mode, "Contador")
