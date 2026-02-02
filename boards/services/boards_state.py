from __future__ import annotations

from dataclasses import dataclass
from django.utils import timezone
from django.db import transaction

from boards.models import Board, Column, Card


@dataclass(frozen=True)
class BoardStateResult:
    ok: bool
    error: str | None = None


@transaction.atomic
def svc_archive_board(board: Board) -> BoardStateResult:
    if board.is_deleted:
        return BoardStateResult(False, "Quadro está na lixeira. Restaure antes de arquivar.")

    if board.is_archived:
        return BoardStateResult(True)

    board.is_archived = True
    board.archived_at = timezone.now()
    board.save(update_fields=["is_archived", "archived_at"])
    return BoardStateResult(True)


@transaction.atomic
def svc_unarchive_board(board: Board) -> BoardStateResult:
    if board.is_deleted:
        return BoardStateResult(False, "Quadro está na lixeira. Restaure antes de desarquivar.")

    if not board.is_archived:
        return BoardStateResult(True)

    board.is_archived = False
    board.archived_at = None
    board.save(update_fields=["is_archived", "archived_at"])
    return BoardStateResult(True)


@transaction.atomic
def svc_soft_delete_board(board: Board) -> BoardStateResult:
    """
    Lixeira do quadro.
    Mantém o board inacessível e fora da home.
    Para evitar “ressuscitar” coisas antigas no restore, registramos o deleted_at e,
    no restore, só restauramos itens com o mesmo timestamp.
    """
    if board.is_deleted:
        return BoardStateResult(True)

    now = timezone.now()

    board.is_deleted = True
    board.deleted_at = now

    # Se estava arquivado e o usuário mandou pra lixeira, padroniza estado
    board.is_archived = False
    board.archived_at = None

    board.save(update_fields=["is_deleted", "deleted_at", "is_archived", "archived_at"])

    # Se o seu fluxo atual já “cascateia” em colunas/cards, mantenha.
    # Aqui fica o padrão: marcar colunas/cards como deletados com o MESMO deleted_at do board.
    Column.objects.filter(board=board, is_deleted=False).update(is_deleted=True, deleted_at=now)
    Card.objects.filter(column__board=board, is_deleted=False).update(is_deleted=True, deleted_at=now)

    return BoardStateResult(True)


@transaction.atomic
def svc_restore_board(board: Board) -> BoardStateResult:
    if not board.is_deleted:
        return BoardStateResult(True)

    board_deleted_at = board.deleted_at

    board.is_deleted = False
    board.deleted_at = None
    board.save(update_fields=["is_deleted", "deleted_at"])

    # Restaura SOMENTE o que foi deletado “junto com o board”
    if board_deleted_at:
        Column.objects.filter(board=board, is_deleted=True, deleted_at=board_deleted_at).update(
            is_deleted=False, deleted_at=None
        )
        Card.objects.filter(column__board=board, is_deleted=True, deleted_at=board_deleted_at).update(
            is_deleted=False, deleted_at=None
        )

    return BoardStateResult(True)
