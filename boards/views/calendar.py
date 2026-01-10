# boards/views/calendar.py

from datetime import date, timedelta
from collections import defaultdict
import calendar

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.utils.dateparse import parse_date

from ..models import Card
from .cards import _user_can_edit_board


def _start_of_week_sunday(d: date) -> date:
    # domingo como início (compatível com seu grid atual)
    return d - timedelta(days=(d.weekday() + 1) % 7)


@login_required
def calendar_cards(request):
    """
    Retorna cards agrupados por data para modo calendário.

    Params:
      - board: int (board_id)           [OBRIGATÓRIO]
      - mode: month | week
      - field: due | start | warn
      - start: YYYY-MM-DD (DATA FOCO; não é mais "grid start")
    """
    mode = request.GET.get("mode", "month")
    field = request.GET.get("field", "due")
    focus_raw = request.GET.get("start")
    board_id = request.GET.get("board")

    if not board_id:
        return JsonResponse({"error": "board is required"}, status=400)

    focus = parse_date(focus_raw) if focus_raw else date.today()

    field_map = {
        "due": "due_date",
        "start": "start_date",
        "warn": "due_warn_date",
    }
    if field not in field_map:
        return JsonResponse({"error": f"invalid field '{field}'"}, status=400)

    field_name = field_map[field]

    # =========================
    # RANGE POR MODO
    # =========================
    if mode == "week":
        week_start = _start_of_week_sunday(focus)
        start = week_start
        end = start + timedelta(days=7)

        meta = {
            "focus": focus.isoformat(),
            "grid_start": start.isoformat(),
            "grid_end": end.isoformat(),
            "focus_year": focus.year,
            "focus_month": focus.month,  # útil pro front manter consistência
            "label": f"Semana de {start.strftime('%d/%m/%Y')}",
        }

    else:
        # modo mês: ancorar no mês do focus
        first_of_month = date(focus.year, focus.month, 1)
        start = _start_of_week_sunday(first_of_month)
        end = start + timedelta(days=42)  # 6 semanas fixo

        last_day = calendar.monthrange(focus.year, focus.month)[1]
        month_start = first_of_month
        month_end = date(focus.year, focus.month, last_day)

        # label pt-BR simples (sem depender de locale do servidor)
        month_names = [
            "", "janeiro", "fevereiro", "março", "abril", "maio", "junho",
            "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"
        ]

        meta = {
            "focus": focus.isoformat(),
            "grid_start": start.isoformat(),
            "grid_end": end.isoformat(),
            "month_start": month_start.isoformat(),
            "month_end": month_end.isoformat(),
            "focus_year": focus.year,
            "focus_month": focus.month,
            "label": f"{month_names[focus.month]} {focus.year}",
        }

    # =========================
    # QUERYSET
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

    grouped = defaultdict(list)

    for card in qs:
        board = card.column.board
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

    return JsonResponse({
        "mode": mode,
        "field": field,
        "days": dict(grouped),
        **meta,
    })
# =======================