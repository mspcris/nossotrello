# boards/views/polling.py

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.template.loader import render_to_string

from ..models import Board, Column
from ..permissions import can_edit_board  # opcional, se quiser alinhar padrão futuramente


@login_required
def board_poll(request, board_id):
    board = get_object_or_404(Board, id=board_id)

    # Segurança: permissão de leitura
    # Mantém compatibilidade com o comportamento atual
    if hasattr(board, "user_can_view"):
        if not board.user_can_view(request.user):
            return JsonResponse({"error": "forbidden"}, status=403)
    else:
        # fallback seguro (caso user_can_view não exista)
        if not board.memberships.filter(user=request.user).exists():
            return JsonResponse({"error": "forbidden"}, status=403)

    # Versão que o cliente já possui
    try:
        client_version = int(request.GET.get("v", 0))
    except (TypeError, ValueError):
        client_version = 0

    # Nada mudou
    if board.version == client_version:
        return JsonResponse({
            "version": board.version,
            "changed": False,
        })

    # Algo mudou → re-renderiza colunas
    columns = (
        Column.objects
        .filter(board=board, is_deleted=False)
        .prefetch_related("cards")
        .order_by("position")
    )

    html = render_to_string(
        "boards/partials/columns_list.html",
        {"columns": columns},
        request=request,
    )

    response = JsonResponse({
        "version": board.version,
        "changed": True,
        "html": html,
    })

    response["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return response

# END boards/views/polling.py
