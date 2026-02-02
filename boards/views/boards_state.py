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
        .filter(is_archived=True, is_deleted=False, boardmembership__user=request.user)
        .order_by("-archived_at", "-id")
        .distinct()
    )
    return render(request, "boards/boards_archived.html", {"boards": boards})


@login_required
@require_POST
def archive_board(request, board_id: int):
    board = get_object_or_404(Board.all_objects, id=board_id)
    if not _user_can_access_board(request.user, board):
        return HttpResponseForbidden("Sem acesso.")

    res = svc_archive_board(board)
    if not res.ok:
        return HttpResponse(res.error or "Falha.", status=400)

    # para htmx: remover card da home
    return HttpResponse("", status=204)


@login_required
@require_POST
def unarchive_board(request, board_id: int):
    board = get_object_or_404(Board.all_objects, id=board_id)
    if not _user_can_access_board(request.user, board):
        return HttpResponseForbidden("Sem acesso.")

    res = svc_unarchive_board(board)
    if not res.ok:
        return HttpResponse(res.error or "Falha.", status=400)

    return HttpResponse("", status=204)


@login_required
@require_POST
def trash_board(request, board_id: int):
    board = get_object_or_404(Board.all_objects, id=board_id)
    if not _user_can_access_board(request.user, board):
        return HttpResponseForbidden("Sem acesso.")

    res = svc_soft_delete_board(board)
    if not res.ok:
        return HttpResponse(res.error or "Falha.", status=400)

    return HttpResponse("", status=204)


@login_required
@require_POST
def restore_board(request, board_id: int):
    board = get_object_or_404(Board.all_objects, id=board_id)
    if not _user_can_access_board(request.user, board):
        return HttpResponseForbidden("Sem acesso.")

    res = svc_restore_board(board)
    if not res.ok:
        return HttpResponse(res.error or "Falha.", status=400)

    return HttpResponse("", status=204)
