# /boards/views/search.py
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import JsonResponse
from django.views.decorators.http import require_GET

from ..models import Board, BoardMembership, Card


@login_required
@require_GET
def board_search(request, board_id: int):
    q_raw = (request.GET.get("q") or "").strip()

    # sem query => "reset" no front (mostra tudo)
    if not q_raw:
        return JsonResponse({"card_ids": [], "column_ids": []})

    # permissão: usuário precisa ter membership no board e board não deletado
    board = Board.objects.filter(id=board_id, is_deleted=False).only("id").first()
    if not board:
        return JsonResponse({"card_ids": [], "column_ids": []}, status=404)

    has_access = BoardMembership.objects.filter(board_id=board_id, user=request.user).exists()
    if not has_access:
        return JsonResponse({"card_ids": [], "column_ids": []}, status=403)

    q = q_raw  # icontains já é case-insensitive

    # escopo: cards ativos + colunas não deletadas dentro do board
    qs = (
        Card.objects
        .filter(column__board_id=board_id, column__is_deleted=False, is_deleted=False)
        .select_related("column")
        .filter(
            Q(title__icontains=q) |
            Q(description__icontains=q) |
            Q(tags__icontains=q) |
            Q(logs__content__icontains=q) |                  # ABA ATIVIDADE (CardLog)
            Q(checklists__title__icontains=q) |              # título do checklist
            Q(checklist_items__text__icontains=q) |          # itens do checklist
            Q(attachments__description__icontains=q) |       # descrição do anexo (se usar)
            Q(attachments__file__icontains=q)                # NOME/PATH do arquivo anexado
        )

        .distinct()
        .only("id", "column_id")
    )

    card_ids = list(qs.values_list("id", flat=True))
    column_ids = sorted(set(qs.values_list("column_id", flat=True)))

    return JsonResponse({
        "card_ids": card_ids,
        "column_ids": column_ids,
    })


@login_required
@require_GET
def home_search(request):
    q_raw = (request.GET.get("q") or "").strip()

    if not q_raw:
        return JsonResponse({"boards": [], "cards": []})

    q = q_raw

    # boards que o usuário tem acesso
    accessible_board_ids_qs = (
        BoardMembership.objects
        .filter(user=request.user, board__is_deleted=False)
        .values_list("board_id", flat=True)
        .distinct()
    )

    # match por nome do board (mantém util)
    matched_boards = (
        Board.objects
        .filter(id__in=accessible_board_ids_qs, is_deleted=False)
        .filter(Q(name__icontains=q))
        .values("id", "name")
        .distinct()
    )

    # match por conteúdo do card (global)
    cards_qs = (
        Card.objects
        .filter(
            column__board_id__in=accessible_board_ids_qs,
            column__is_deleted=False,
            is_deleted=False,
        )
        .select_related("column", "column__board")
        .filter(
            Q(title__icontains=q) |
            Q(description__icontains=q) |
            Q(tags__icontains=q) |
            Q(logs__content__icontains=q) |
            Q(checklists__title__icontains=q) |
            Q(checklist_items__text__icontains=q) |
            Q(attachments__description__icontains=q) |
            Q(attachments__file__icontains=q)
        )
        .distinct()
        .only("id", "title", "column_id", "column__board_id")
    )

    # payload leve (sem HTML), pronto pro front renderizar
    cards = []
    for c in cards_qs[:80]:  # limite pra não explodir UI
        board_id = getattr(c.column, "board_id", None)
        cards.append({
            "id": c.id,
            "title": c.title or "(sem título)",
            "board_id": board_id,
        })

    boards = list(matched_boards[:40])

    return JsonResponse({
        "boards": boards,
        "cards": cards,
    })
