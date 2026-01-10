from datetime import date, timedelta
from collections import defaultdict

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.utils.dateparse import parse_date

from ..models import Card
from .cards import _user_can_edit_board


@login_required
def calendar_cards(request):
    """
    Retorna cards agrupados por data para modo calendário.
    Params:
      - mode: month | week
      - field: due | start | warn
      - start: YYYY-MM-DD (início do range)
    """
    mode = request.GET.get("mode", "month")
    field = request.GET.get("field", "due")
    start_raw = request.GET.get("start")

    start = parse_date(start_raw) if start_raw else date.today()

    # sempre começa no domingo
    start = start - timedelta(days=(start.weekday() + 1) % 7)

    if mode == "week":
        end = start + timedelta(days=7)
    else:
        end = start + timedelta(days=42)  # 6 semanas (grid fixo)

    field_map = {
        "due": "due_date",
        "start": "start_date",
        "warn": "due_warn_date",
    }
    field_name = field_map.get(field, "due_date")

    qs = (
        Card.objects
        .filter(**{f"{field_name}__gte": start, f"{field_name}__lt": end})
        .select_related("column", "column__board")
    )

    grouped = defaultdict(list)

    for card in qs:
        board = card.column.board
        if not _user_can_edit_board(request.user, board):
            continue

        d = getattr(card, field_name)
        if not d:
            continue

        grouped[d.isoformat()].append({
            "id": card.id,
            "title": card.title,
            "board": board.name,
            "column": card.column.name,
            "due_date": card.due_date,
            "start_date": card.start_date,
            "warn_date": card.due_warn_date,
        })

    return JsonResponse({
        "start": start.isoformat(),
        "end": end.isoformat(),
        "mode": mode,
        "field": field,
        "days": grouped,
    })
