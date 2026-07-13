"""
Endpoints de edição colaborativa (soft lock + preview ao vivo).

Fluxo:

    focus  -> POST /card/<id>/field/<name>/lock/      -> 200 ok   | 409 conflict
    input  -> POST /card/<id>/field/<name>/typing/    -> 200 ok   (throttled no client)
    blur   -> POST /card/<id>/field/<name>/release/   -> 200 ok   (salva no DB)

Campos suportados no MVP: `title`, `description`.

Cada endpoint publica um evento via RabbitMQ → bridge → grupo `board_<id>`
→ BoardConsumer → navegadores dos outros usuários:

    card.field.locked     { board_id, card_id, field, user, value }
    card.field.typing     { board_id, card_id, field, user, value }
    card.field.released   { board_id, card_id, field, user, value }

O consumer é pass-through; o dispatch por evento mora no board.ws.js.
"""

from __future__ import annotations

import logging

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_POST

from boards.models import Card
from boards.permissions import can_edit_board
from boards.services import edit_locks
from boards.services.pubsub_service import publish_event
from boards.views.helpers import _save_base64_images_to_media, sanitize_quill_html

logger = logging.getLogger(__name__)

ALLOWED_FIELDS = {"title", "description"}


def _user_info(user) -> dict:
    return {
        "id": int(getattr(user, "id", 0) or 0),
        "username": getattr(user, "username", "") or "",
        "display_name": (
            getattr(user, "get_full_name", lambda: "")() or getattr(user, "username", "")
        ),
    }


def _board_id_of(card: Card) -> int:
    return int(card.column.board_id)


def _publish(event_type: str, board_id: int, card_id: int, field: str, user, value: str):
    try:
        publish_event(
            event_type,
            board_id=board_id,
            card_id=card_id,
            field=field,
            user=_user_info(user),
            value=value,
        )
    except Exception:  # noqa: BLE001
        logger.debug("publish %s falhou", event_type, exc_info=True)


def _check_field(field: str):
    if field not in ALLOWED_FIELDS:
        return JsonResponse(
            {"ok": False, "error": "field_not_allowed", "field": field},
            status=400,
        )
    return None


def _check_perm(request, card: Card):
    """
    Exige que o usuário possa editar o board. Viewers caem em 403.
    """
    board = card.column.board
    if not can_edit_board(request.user, board):
        return JsonResponse({"ok": False, "error": "forbidden"}, status=403)
    return None


# ----------------------------------------------------------------------
# LOCK
# ----------------------------------------------------------------------
@login_required
@require_POST
def card_field_lock(request, card_id: int, field: str):
    err = _check_field(field)
    if err:
        return err

    card = get_object_or_404(Card, id=card_id)
    err = _check_perm(request, card)
    if err:
        return err

    board_id = _board_id_of(card)
    value = request.POST.get("value", "") or ""

    acquired, holder = edit_locks.acquire(
        card_id=card.id,
        field=field,
        user_id=request.user.id,
        username=request.user.username or f"user{request.user.id}",
    )

    if not acquired:
        return JsonResponse(
            {
                "ok": False,
                "error": "locked",
                "holder": holder or {},
            },
            status=409,
        )

    _publish(
        "card.field.locked",
        board_id=board_id,
        card_id=card.id,
        field=field,
        user=request.user,
        value=value,
    )

    return JsonResponse({"ok": True, "holder": holder or _user_info(request.user)})


# ----------------------------------------------------------------------
# TYPING
# ----------------------------------------------------------------------
@login_required
@require_POST
def card_field_typing(request, card_id: int, field: str):
    err = _check_field(field)
    if err:
        return err

    card = get_object_or_404(Card, id=card_id)
    err = _check_perm(request, card)
    if err:
        return err

    board_id = _board_id_of(card)
    value = request.POST.get("value", "") or ""

    # Renova TTL. Se não for dono, devolve 409 para o client re-acquire.
    ok = edit_locks.refresh(card.id, field, request.user.id)
    if not ok:
        holder = edit_locks.get_holder(card.id, field)
        return JsonResponse(
            {"ok": False, "error": "not_lock_holder", "holder": holder or {}},
            status=409,
        )

    _publish(
        "card.field.typing",
        board_id=board_id,
        card_id=card.id,
        field=field,
        user=request.user,
        value=value,
    )
    return JsonResponse({"ok": True})


# ----------------------------------------------------------------------
# RELEASE (salva + libera lock)
# ----------------------------------------------------------------------
@login_required
@require_POST
def card_field_release(request, card_id: int, field: str):
    err = _check_field(field)
    if err:
        return err

    card = get_object_or_404(Card, id=card_id)
    err = _check_perm(request, card)
    if err:
        return err

    board_id = _board_id_of(card)
    raw_value = request.POST.get("value", "") or ""

    # Só salva se o caller é quem detém o lock. Se não tem lock (refresh falha)
    # por qualquer motivo (redis down, ttl expirou), ainda salvamos o valor —
    # release é sempre best-effort.
    _ = edit_locks.refresh(card.id, field, request.user.id)

    # Persiste no banco
    final_value = raw_value
    with transaction.atomic():
        if field == "title":
            cleaned = (raw_value or "").strip()
            if cleaned:
                card.title = cleaned[:255]
                card.save(update_fields=["title"])
                final_value = card.title
        elif field == "description":
            # Extrai base64 → media (mesma pipeline do update_card)
            try:
                new_html, _saved = _save_base64_images_to_media(raw_value, folder="quill")
            except Exception:  # noqa: BLE001
                logger.warning(
                    "release description: _save_base64_images_to_media falhou",
                    exc_info=True,
                )
                new_html = raw_value
            card.description = sanitize_quill_html((new_html or "").strip())
            card.save(update_fields=["description"])
            final_value = card.description

    # Libera o lock
    edit_locks.release(card.id, field, request.user.id)

    _publish(
        "card.field.released",
        board_id=board_id,
        card_id=card.id,
        field=field,
        user=request.user,
        value=final_value,
    )

    return JsonResponse({"ok": True, "value": final_value})
