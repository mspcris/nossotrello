# boards/views/polling.py

from django.contrib.auth.decorators import login_required
from django.db.models import Count, Prefetch
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.template.loader import render_to_string

from ..models import Board, Column, Card


@login_required
def board_poll(request, board_id):
    board = get_object_or_404(Board, id=board_id)

    # ============================================================
    # Segurança: permissão de leitura (compatível + fallback seguro)
    # ============================================================
    if hasattr(board, "user_can_view"):
        if not board.user_can_view(request.user):
            return JsonResponse({"error": "forbidden"}, status=403)
    else:
        if not board.memberships.filter(user=request.user).exists():
            return JsonResponse({"error": "forbidden"}, status=403)

    # ============================================================
    # Versão que o cliente já possui
    # ============================================================
    try:
        client_version = int(request.GET.get("v", 0))
    except (TypeError, ValueError):
        client_version = 0

    # Nada mudou
    if int(board.version or 0) == client_version:
        resp = JsonResponse({"version": board.version, "changed": False})
        resp["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        return resp

    # ============================================================
    # Algo mudou -> re-renderiza colunas
    # IMPORTANT:
    # - entregue "board" no contexto (mantém Coluna Agregadora)
    # - entregue as MESMAS contagens que o template usa (card_count)
    # ============================================================

    # Prefetch de cards (ordem consistente ajuda o drag/poll a não “piscar”)
    cards_qs = Card.objects.filter(is_deleted=False).order_by("position", "id")

    columns = (
        Column.objects
        .filter(board=board, is_deleted=False)
        .annotate(card_count=Count("cards", distinct=True))
        .prefetch_related(Prefetch("cards", queryset=cards_qs))
        .order_by("position", "id")
    )

    html = render_to_string(
        "boards/partials/columns_list.html",
        {
            "columns": columns,
            "board": board,  # ✅ ESSENCIAL p/ manter a agregadora estável
        },
        request=request,
    )

    resp = JsonResponse(
        {
            "version": board.version,
            "changed": True,
            "html": html,
        }
    )
    resp["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return resp

# END boards/views/polling.py
