from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, render, redirect
from django.views.decorators.http import require_POST

from boards.models import Board, BoardMembership
from boards.services.boards_state import (
    svc_archive_board,
    svc_unarchive_board,
    svc_soft_delete_board,
    svc_restore_board,
)


def _user_can_access_board(user, board: Board) -> bool:
    return BoardMembership.objects.filter(user=user, board=board).exists()


def _user_can_edit_board(user, board: Board) -> bool:
    """Escrita (arquivar/lixeira/restaurar o quadro): owner/editor/staff; viewer não."""
    if not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_staff", False):
        return True
    bm = BoardMembership.objects.filter(board=board, user=user).first()
    if bm:
        return bm.role in {BoardMembership.Role.OWNER, BoardMembership.Role.EDITOR}
    return bool(getattr(board, "created_by_id", None) == getattr(user, "id", None))


@login_required
def boards_trash(request):
    boards = (
        Board.all_objects
        .filter(is_deleted=True, memberships__user=request.user).distinct()
        .order_by("-deleted_at", "-id")
        .distinct()
    )
    return render(request, "boards/boards_trash.html", {"boards": boards})


@login_required
def boards_archived(request):
    boards = (
        Board.all_objects
        .filter(
            is_archived=True,
            is_deleted=False,
            memberships__user=request.user,  # FIX: era boardmembership__user
        )
        .order_by("-archived_at", "-id")
        .distinct()
    )
    return render(request, "boards/boards_archived.html", {"boards": boards})



@login_required
@require_POST
def archive_board(request, board_id: int):
    board = get_object_or_404(Board.all_objects, id=board_id)
    if not _user_can_edit_board(request.user, board):
        return HttpResponseForbidden("Sem permissão de edição neste board.")

    res = svc_archive_board(board)
    if not res.ok:
        return HttpResponse(res.error or "Falha.", status=400)

    # para htmx: remover card da home
    return HttpResponse("", status=204)


@login_required
@require_POST
def unarchive_board(request, board_id: int):
    board = get_object_or_404(Board.all_objects, id=board_id)
    if not _user_can_edit_board(request.user, board):
        return HttpResponseForbidden("Sem permissão de edição neste board.")

    res = svc_unarchive_board(board)
    if not res.ok:
        return HttpResponse(res.error or "Falha.", status=400)

    return HttpResponse("", status=204)


@login_required
@require_POST
def trash_board(request, board_id: int):
    board = get_object_or_404(Board.all_objects, id=board_id)
    if not _user_can_edit_board(request.user, board):
        return HttpResponseForbidden("Sem permissão de edição neste board.")

    res = svc_soft_delete_board(board)
    if not res.ok:
        return HttpResponse(res.error or "Falha.", status=400)

    return HttpResponse("", status=204)


@login_required
@require_POST
def restore_board(request, board_id: int):
    board = get_object_or_404(Board.all_objects, id=board_id)
    if not _user_can_edit_board(request.user, board):
        return HttpResponseForbidden("Sem permissão de edição neste board.")

    res = svc_restore_board(board)
    if not res.ok:
        return HttpResponse(res.error or "Falha.", status=400)

    return HttpResponse("", status=204)
