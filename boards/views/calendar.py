# boards/views/calendar.py

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
      - board: int (board_id)           [OBRIGATÓRIO]
      - mode: month | week
      - field: due | start | warn
      - start: YYYY-MM-DD (início do range)
    """

    # =========================
    # PARAMS
    # =========================
    mode = request.GET.get("mode", "month")
    field = request.GET.get("field", "due")
    start_raw = request.GET.get("start")
    board_id = request.GET.get("board")

    if not board_id:
        return JsonResponse(
            {"error": "board is required"},
            status=400
        )

    # =========================
    # START / END RANGE
    # =========================
    start = parse_date(start_raw) if start_raw else date.today()

    # sempre começa no domingo
    start = start - timedelta(days=(start.weekday() + 1) % 7)

    if mode == "week":
        end = start + timedelta(days=7)
    else:
        end = start + timedelta(days=42)  # grid fixo (6 semanas)

    # =========================
    # FIELD MAP (MODEL REAL)
    # =========================
    field_map = {
    "due": "due_date",
    "start": "start_date",
    "warn": "due_warn_date",
}


    if field not in field_map:
        return JsonResponse(
            {"error": f"invalid field '{field}'"},
            status=400
        )
    
    field_name = field_map[field]

    # =========================
    # QUERYSET (CRÍTICO)
    # =========================
    qs = (
        Card.objects
        .filter(
            column__board_id=board_id,
            is_deleted=False,
            **{
                f"{field_name}__gte": start,
                f"{field_name}__lt": end,
            }
        )
        .select_related("column", "column__board")
    )

    # =========================
    # GROUP BY DAY
    # =========================
    grouped = defaultdict(list)

    for card in qs:
        board = card.column.board

        # segurança extra (não deveria falhar, mas mantém consistência do projeto)
        if not _user_can_edit_board(request.user, board):
            continue

        d = getattr(card, field_name, None)
        if not d:
            continue

        due_date = getattr(card, "due_date", None)
        start_date = getattr(card, "start_date", None)
        warn_date = getattr(card, "due_warn_date", None)

        grouped[d.isoformat()].append({
            "id": card.id,
            "title": card.title,
            "column": card.column.name,
            "due_date": due_date.isoformat() if due_date else None,
            "start_date": start_date.isoformat() if start_date else None,
            "warn_date": warn_date.isoformat() if warn_date else None,
        })


    # =========================
    # RESPONSE
    # =========================
    return JsonResponse({
        "start": start.isoformat(),
        "end": end.isoformat(),
        "mode": mode,
        "field": field,
        "days": dict(grouped),
    })
