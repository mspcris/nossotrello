# boards/services/cards_state.py
from django.utils import timezone


def archive_card(card):
    if card.is_deleted:
        return
    if card.is_archived:
        return
    card.is_archived = True
    card.archived_at = timezone.now()
    card.save(update_fields=["is_archived", "archived_at"])


def unarchive_card(card):
    if card.is_archived is False:
        return
    card.is_archived = False
    card.archived_at = None
    card.save(update_fields=["is_archived", "archived_at"])


def soft_delete_card(card):
    if card.is_deleted:
        return
    card.is_deleted = True
    card.deleted_at = timezone.now()
    card.save(update_fields=["is_deleted", "deleted_at"])


def restore_card(card):
    if card.is_deleted is False:
        return
    card.is_deleted = False
    card.deleted_at = None
    card.save(update_fields=["is_deleted", "deleted_at"])
# END boards/services/cards_state.py