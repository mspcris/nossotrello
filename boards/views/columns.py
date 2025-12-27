# boards/views/columns.py

import json

from django.http import HttpResponse, JsonResponse, HttpResponseBadRequest
from django.shortcuts import render, get_object_or_404
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.utils import timezone
from django.utils.html import escape

from ..forms import ColumnForm
from .helpers import (
    # mantém só helpers/models que realmente estão em helpers.py
    # exemplo:
    _actor_label,
    _log_board,
    _log_card,
    Board,
    Column,
    Card,
    BoardMembership,
)



def add_column(request, board_id):
    board = get_object_or_404(Board, id=board_id)

    if request.method == "POST":
        form = ColumnForm(request.POST)
        if form.is_valid():
            column = form.save(commit=False)
            column.board = board
            column.position = board.columns.count()
            column.save()
            board.version += 1
            board.save(update_fields=["version"])


            actor = _actor_label(request)
            _log_board(
                board,
                request,
                f"<p><strong>{actor}</strong> criou a coluna <strong>{escape(column.name)}</strong> no quadro <strong>{escape(board.name)}</strong>.</p>",
            )

            return render(request, "boards/partials/column_item.html", {"column": column})

        return HttpResponse("Erro ao criar coluna.", status=400)

    return render(
        request,
        "boards/partials/add_column_form.html",
        {"board": board, "form": ColumnForm()},
    )


@require_POST
def set_column_theme(request, column_id):
    column = get_object_or_404(Column, id=column_id)
    theme = request.POST.get("theme")

    valid_themes = [t[0] for t in Column.THEME_CHOICES]
    if theme not in valid_themes:
        return HttpResponse("Tema inválido", status=400)

    old_theme = getattr(column, "theme", "")
    column.theme = theme
    column.save(update_fields=["theme"])

    board = column.board
    board.version += 1
    board.save(update_fields=["version"])

    actor = _actor_label(request)
    _log_board(
        column.board,
        request,
        f"<p><strong>{actor}</strong> alterou o tema da coluna <strong>{escape(column.name)}</strong> de <strong>{escape(old_theme)}</strong> para <strong>{escape(theme)}</strong>.</p>",
    )

    return render(request, "boards/partials/column_item.html", {"column": column})


@login_required
@require_POST
def reorder_columns(request, board_id):
    board = get_object_or_404(Board, id=board_id, is_deleted=False)

    try:
        payload = json.loads(request.body.decode("utf-8"))
        order = payload.get("order", [])
        if not isinstance(order, list):
            return JsonResponse({"ok": False, "error": "order inválido"}, status=400)
        order = [int(x) for x in order]
    except Exception:
        return JsonResponse({"ok": False, "error": "JSON inválido"}, status=400)

    cols = Column.objects.filter(board=board, is_deleted=False)
    cols_map = {c.id: c for c in cols}

    if any(cid not in cols_map for cid in order):
        return JsonResponse({"ok": False, "error": "coluna fora do board"}, status=400)

    with transaction.atomic():
        for idx, cid in enumerate(order):
            Column.objects.filter(id=cid, board=board).update(position=idx)

        board.version += 1
        board.save(update_fields=["version"])


    actor = _actor_label(request)
    _log_board(
        board,
        request,
        f"<p><strong>{actor}</strong> reordenou colunas no quadro <strong>{escape(board.name)}</strong>.</p>",
    )

    return JsonResponse({"ok": True})

@require_POST
def rename_column(request, column_id):
    column = get_object_or_404(Column, id=column_id)
    board = column.board
    actor = _actor_label(request)

    old_name = column.name
    name = request.POST.get("name", "").strip()
    if not name:
        return HttpResponse("Nome inválido", status=400)
    
    column.name = name
    column.save(update_fields=["name"])
    board.version += 1
    board.save(update_fields=["version"])
    
    for c in Card.objects.filter(column=column, is_deleted=False):
        _log_card(
            c,
            request,
            f"<p><strong>{actor}</strong> renomeou a coluna de <strong>{escape(old_name)}</strong> para <strong>{escape(name)}</strong>.</p>",
        )

    _log_board(
        column.board,
        request,
        f"<p><strong>{actor}</strong> renomeou a coluna de <strong>{escape(old_name)}</strong> para <strong>{escape(name)}</strong>.</p>",
    )
        
    return render(request, "boards/partials/column_item.html", {"column": column})
    


def delete_column(request, column_id):
    if request.method != "POST":
        return HttpResponseBadRequest("Método inválido.")

    try:
        column = Column.objects.get(id=column_id, is_deleted=False)
    except Column.DoesNotExist:
        return HttpResponseBadRequest("Coluna não encontrada.")


    board = column.board
    actor = _actor_label(request)

    cards_in_col = Card.objects.filter(column=column, is_deleted=False)
    for c in cards_in_col:
        _log_card(
            c,
            request,
            f"<p><strong>{actor}</strong> excluiu (soft delete) a coluna <strong>{escape(column.name)}</strong>, removendo este card da visualização.</p>",
        )

    _log_board(
        column.board,
        request,
        f"<p><strong>{actor}</strong> excluiu (soft delete) a coluna <strong>{escape(column.name)}</strong>.</p>",
    )

    now = timezone.now()
    column.is_deleted = True
    column.deleted_at = now
    column.save(update_fields=["is_deleted", "deleted_at"])
    board.version += 1
    board.save(update_fields=["version"])

    Card.objects.filter(column=column, is_deleted=False).update(is_deleted=True, deleted_at=now)
    return HttpResponse("")


# alias de compatibilidade
column_delete = delete_column
