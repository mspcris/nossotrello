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
from django.utils.html import escape

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


def _can_edit_board(user, board: Board) -> bool:
    """Escrita (arquivar/lixeira/restaurar): owner/editor/staff; viewer não."""
    if not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_staff", False):
        return True
    bm = BoardMembership.objects.filter(board=board, user=user).first()
    if bm:
        return bm.role in {BoardMembership.Role.OWNER, BoardMembership.Role.EDITOR}
    return bool(getattr(board, "created_by_id", None) == getattr(user, "id", None))


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

    if not _can_edit_board(request.user, board):
        return HttpResponseForbidden("Sem permissão de edição neste board.")

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

    if not _can_edit_board(request.user, board):
        return HttpResponseForbidden("Sem permissão de edição neste board.")

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

    if not _can_edit_board(request.user, board):
        return HttpResponseForbidden("Sem permissão de edição neste board.")

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

    if not _can_edit_board(request.user, board):
        return HttpResponseForbidden("Sem permissão de edição neste board.")

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


# ======================================================================
# IMPEDIMENTO — card travado esperando alguém
# ======================================================================

def _is_board_owner(user, board: Board) -> bool:
    """Dono do quadro (ou staff). Editor NÃO conta aqui."""
    if not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_staff", False):
        return True
    bm = BoardMembership.objects.filter(board=board, user=user).first()
    if bm and bm.role == BoardMembership.Role.OWNER:
        return True
    return bool(getattr(board, "created_by_id", None) == getattr(user, "id", None))


def _bump_board_version(board):
    """Dispara o realtime (post_save do Board publica board.invalidated)."""
    try:
        board.version = int(getattr(board, "version", 0) or 0) + 1
        board.save(update_fields=["version"])
    except Exception:
        pass


def _impediment_state(card):
    """(is_impeded, [user_ids ativos]) — fonte de verdade a partir da tabela."""
    from boards.models import CardImpediment

    ids = list(
        CardImpediment.objects.filter(card_id=card.id, is_active=True)
        .values_list("user_id", flat=True)
    )
    return bool(ids), ids


@login_required
@require_http_methods(["POST"])
def set_card_impediment(request, card_id: int):
    """Marca o card como impedido, apontando 1+ responsáveis (membros do board).

    POST responsibles=<id>&responsibles=<id>... Exige pelo menos um. Reativa
    pendência que o próprio responsável já tinha resolvido antes.
    """
    from django.utils import timezone

    from boards.models import BoardMembership, CardImpediment
    from boards.views.helpers import _log_card, _person_display_name

    card = get_object_or_404(Card.objects.select_related("column__board"), id=card_id)
    board = card.column.board

    if not _can_edit_board(request.user, board):
        return HttpResponseForbidden("Sem permissão para marcar impedimento neste card.")

    raw = request.POST.getlist("responsibles") or request.POST.getlist("responsibles[]")
    try:
        wanted = {int(x) for x in raw if str(x).strip()}
    except (TypeError, ValueError):
        return HttpResponseBadRequest("Responsáveis inválidos.")

    if not wanted:
        return HttpResponseBadRequest("Selecione ao menos um responsável pelo impedimento.")

    # só quem é membro do board pode ser responsável
    valid_ids = set(
        BoardMembership.objects.filter(board=board, user_id__in=wanted)
        .values_list("user_id", flat=True)
    )
    invalid = wanted - valid_ids
    if invalid:
        return HttpResponseBadRequest("Só participantes do quadro podem ser responsáveis.")

    created_names = []
    for uid in valid_ids:
        obj, created = CardImpediment.objects.get_or_create(
            card_id=card.id,
            user_id=uid,
            is_active=True,
            defaults={"created_by": request.user},
        )
        if created:
            created_names.append(_person_display_name(obj.user))

    if not card.is_impeded:
        card.is_impeded = True
        card.save(update_fields=["is_impeded"])

    if created_names:
        nomes = ", ".join(escape(n) for n in created_names)
        _log_card(
            card, request,
            f"<p>Card marcado como <strong>impedido</strong> — aguardando: <strong>{nomes}</strong>.</p>",
        )

    _bump_board_version(board)
    is_impeded, ids = _impediment_state(card)
    return JsonResponse({"ok": True, "is_impeded": is_impeded, "responsibles": ids})


@login_required
@require_http_methods(["POST"])
def clear_card_impediment(request, card_id: int):
    """Resolve a pendência de UM responsável.

    O próprio responsável resolve a sua; o dono/editor do quadro resolve a de
    qualquer um. POST user_id=<id> (default: o próprio request.user). Quando não
    sobra pendência ativa, o card sai do impedimento.
    """
    from django.utils import timezone

    from boards.models import CardImpediment
    from boards.views.helpers import _log_card, _person_display_name

    card = get_object_or_404(Card.objects.select_related("column__board"), id=card_id)
    board = card.column.board

    if not _can_access_board(request.user, board):
        return HttpResponseForbidden("Sem acesso ao board deste card.")

    try:
        target_id = int(request.POST.get("user_id") or request.user.id)
    except (TypeError, ValueError):
        return HttpResponseBadRequest("Usuário inválido.")

    # o próprio responsável resolve a sua; a de OUTRO só o dono do quadro (ou
    # staff) — editor comum não, como o Cristiano pediu.
    is_self = target_id == request.user.id
    if not is_self and not _is_board_owner(request.user, board):
        return HttpResponseForbidden("Só o próprio responsável ou o dono do quadro pode remover.")

    imp = CardImpediment.objects.filter(
        card_id=card.id, user_id=target_id, is_active=True
    ).first()
    if not imp:
        return JsonResponse({"ok": True, "is_impeded": card.is_impeded, "changed": False})

    imp.is_active = False
    imp.resolved_at = timezone.now()
    imp.resolved_by = request.user
    imp.save(update_fields=["is_active", "resolved_at", "resolved_by"])

    is_impeded, ids = _impediment_state(card)
    if not is_impeded and card.is_impeded:
        card.is_impeded = False
        card.save(update_fields=["is_impeded"])

    quem = _person_display_name(imp.user)
    _log_card(
        card, request,
        f"<p>Pendência de <strong>{escape(quem)}</strong> resolvida"
        f"{' — card liberado.' if not is_impeded else '.'}</p>",
    )

    _bump_board_version(board)
    return JsonResponse({"ok": True, "is_impeded": is_impeded, "responsibles": ids, "changed": True})


# END boards/views/cards_state.py
