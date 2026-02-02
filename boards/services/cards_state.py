# boards/services/cards_state.py
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from boards.models import Card, Column


RECOVERY_COLUMN_NAME = "CARD RECUPERADO"


def archive_card(card: Card):
    card.is_archived = True
    card.archived_at = timezone.now()
    card.save(update_fields=["is_archived", "archived_at"])


def unarchive_card(card: Card):
    # Desarquivar sempre devolve para uma coluna "visível"
    target_column = _ensure_visible_column(card)

    card.is_archived = False
    card.archived_at = None

    # Se mudou de coluna, recalcula posição no destino
    card.column = target_column
    card.position = _next_card_position(target_column)

    card.save(update_fields=["is_archived", "archived_at", "column", "position"])


def soft_delete_card(card: Card):
    card.is_deleted = True
    card.deleted_at = timezone.now()
    card.save(update_fields=["is_deleted", "deleted_at"])


def restore_card(card: Card):
    # Restaurar da lixeira sempre devolve para uma coluna "visível"
    target_column = _ensure_visible_column(card)

    card.is_deleted = False
    card.deleted_at = None

    # Se mudou de coluna, recalcula posição no destino
    card.column = target_column
    card.position = _next_card_position(target_column)

    card.save(update_fields=["is_deleted", "deleted_at", "column", "position"])


# ==========================
# Internals
# ==========================
@transaction.atomic
def _ensure_visible_column(card: Card) -> Column:
    """
    Regra:
    - Se card.column existe e NÃO está deletada => mantém.
    - Caso contrário => usa/cria coluna 'CARD RECUPERADO' no mesmo board.
    """
    col = getattr(card, "column", None)
    if col is not None and getattr(col, "is_deleted", False) is False:
        return col

    board = None
    # Preferência: coluna (mesmo deletada) ainda aponta para o board
    if col is not None:
        board = getattr(col, "board", None)

    # Fallback: se o seu Card tiver FK direta p/ Board (se existir no seu modelo)
    if board is None and hasattr(card, "board"):
        board = getattr(card, "board", None)

    if board is None:
        # Sem board não tem como recuperar corretamente sem alterar model/DB
        raise ValueError("Card sem board resolvível para recuperação.")

    return _get_or_create_recovery_column(board)


def _get_or_create_recovery_column(board) -> Column:
    col = (
        Column.objects
        .filter(board=board, name=RECOVERY_COLUMN_NAME, is_deleted=False)
        .first()
    )
    if col:
        return col

    next_pos = _next_column_position(board)
    # Se seu Column tiver outros campos obrigatórios, complete aqui.
    return Column.objects.create(
        board=board,
        name=RECOVERY_COLUMN_NAME,
        position=next_pos,
        is_deleted=False,
        deleted_at=None,
    )


def _next_column_position(board) -> int:
    m = Column.objects.filter(board=board).aggregate(mx=Max("position"))["mx"]
    return (m or 0) + 1


def _next_card_position(column: Column) -> int:
    m = Card.all_objects.filter(column=column).aggregate(mx=Max("position"))["mx"]
    return (m or 0) + 1
