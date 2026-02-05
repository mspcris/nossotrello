# boards/views/cards_state.py
from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import (
    HttpResponse,
    HttpResponseForbidden,
    HttpResponseBadRequest,
)
from django.shortcuts import get_object_or_404, render, redirect
from django.urls import reverse
from django.views.decorators.http import require_POST, require_http_methods

from boards.models import Board, BoardMembership, Card
from boards.services.cards_state import (
    archive_card as svc_archive_card,
    unarchive_card as svc_unarchive_card,
    soft_delete_card as svc_soft_delete_card,
    restore_card as svc_restore_card,
)
from boards.models import CardFollow, UserProfile
from django.http import HttpResponseBadRequest, HttpResponseForbidden, JsonResponse, HttpResponse



def _can_access_board(user, board: Board) -> bool:
    if not user.is_authenticated:
        return False
    return BoardMembership.objects.filter(board=board, user=user).exists()


def _htmx_refresh_or_204(request):
    # Se for HTMX: manda refresh da página
    if request.headers.get("HX-Request"):
        resp = HttpResponse(status=204)
        resp["HX-Refresh"] = "true"
        return resp
    return None


def _resolve_board_from_card(card: Card) -> Board | None:
    """
    Resolve o Board de forma segura.
    - Preferência: card.column.board (inclusive se a coluna estiver soft-deleted)
    - Fallback: card.board (se existir no seu modelo)
    """
    col = getattr(card, "column", None)
    if col is not None and getattr(col, "board", None) is not None:
        return col.board

    if hasattr(card, "board") and getattr(card, "board", None) is not None:
        return card.board

    return None


def _redirect_board_or_ok(request, board_id: int):
    # Tenta usar reverse se existir; se não, cai no path padrão
    try:
        url = reverse("boards:board_detail", args=[board_id])
    except Exception:
        url = f"/board/{board_id}/"

    if request.headers.get("HX-Request"):
        resp = HttpResponse(status=204)
        resp["HX-Redirect"] = url
        return resp

    return redirect(url)


@require_POST
@login_required
def archive_card(request, card_id: int):
    card = get_object_or_404(
        Card.all_objects.select_related("column__board"),
        pk=card_id,
    )
    board = _resolve_board_from_card(card)
    if board is None:
        return HttpResponseBadRequest("Não foi possível resolver o board do card para esta ação.")

    if not _can_access_board(request.user, board):
        return HttpResponseForbidden("Sem acesso a este board.")

    svc_archive_card(card)
    return _redirect_board_or_ok(request, board.id)


@require_POST
@login_required
def unarchive_card(request, card_id: int):
    card = get_object_or_404(
        Card.all_objects.select_related("column__board"),
        pk=card_id,
    )
    board = _resolve_board_from_card(card)
    if board is None:
        return HttpResponseBadRequest("Não foi possível resolver o board do card para esta ação.")

    if not _can_access_board(request.user, board):
        return HttpResponseForbidden("Sem acesso a este board.")

    # service já deve garantir coluna visível (CARD RECUPERADO se necessário)
    svc_unarchive_card(card)

    h = _htmx_refresh_or_204(request)
    return h or HttpResponse("OK")


@require_POST
@login_required
def trash_card(request, card_id: int):
    card = get_object_or_404(
        Card.all_objects.select_related("column__board"),
        pk=card_id,
    )
    board = _resolve_board_from_card(card)
    if board is None:
        return HttpResponseBadRequest("Não foi possível resolver o board do card para esta ação.")

    if not _can_access_board(request.user, board):
        return HttpResponseForbidden("Sem acesso a este board.")

    svc_soft_delete_card(card)
    return _redirect_board_or_ok(request, board.id)


@require_POST
@login_required
def restore_card(request, card_id: int):
    card = get_object_or_404(
        Card.all_objects.select_related("column__board"),
        pk=card_id,
    )
    board = _resolve_board_from_card(card)
    if board is None:
        return HttpResponseBadRequest("Não foi possível resolver o board do card para esta ação.")

    if not _can_access_board(request.user, board):
        return HttpResponseForbidden("Sem acesso a este board.")

    # service já deve garantir coluna visível (CARD RECUPERADO se necessário)
    svc_restore_card(card)

    h = _htmx_refresh_or_204(request)
    return h or HttpResponse("OK")


@login_required
def trash(request, board_id: int):
    board = get_object_or_404(Board, pk=board_id)

    if not _can_access_board(request.user, board):
        return HttpResponseForbidden("Sem acesso a este board.")

    cards = (
        Card.all_objects.filter(column__board=board, is_deleted=True)
        .select_related("column")
        .order_by("-deleted_at", "-id")
    )

    return render(request, "boards/trash.html", {"board": board, "cards": cards})


@login_required
def archived(request, board_id: int):
    board = get_object_or_404(Board, pk=board_id)

    if not _can_access_board(request.user, board):
        return HttpResponseForbidden("Sem acesso a este board.")

    cards = (
        Card.all_objects.filter(column__board=board, is_archived=True, is_deleted=False)
        .select_related("column")
        .order_by("-archived_at", "-id")
    )

    return render(request, "boards/archived.html", {"board": board, "cards": cards})


@login_required
@require_http_methods(["POST"])
def toggle_card_follow(request, card_id: int):
    card = get_object_or_404(Card.objects.select_related("column__board"), id=card_id)
    board = card.column.board

    # permissão: tem que ver o board
    if not _can_access_board(request.user, board):
        return HttpResponseForbidden("Sem acesso ao board deste card")

    # gate: só pode seguir se tiver email OU whatsapp habilitado no profile
    prof = getattr(request.user, "profile", None)
    if not prof:
        prof, _ = UserProfile.objects.get_or_create(user=request.user)

    can_follow = bool(getattr(prof, "notify_email", False) or getattr(prof, "notify_whatsapp", False))
    if not can_follow:
        return HttpResponseBadRequest("Habilite Email ou WhatsApp no seu perfil para seguir cards.")

    obj = CardFollow.objects.filter(card_id=card.id, user_id=request.user.id).first()
    if obj:
        obj.delete()
        return JsonResponse({"ok": True, "following": False})
    else:
        CardFollow.objects.create(card_id=card.id, user_id=request.user.id)
        return JsonResponse({"ok": True, "following": True})

# END boards/views/cards_state.py
