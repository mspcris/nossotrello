# boards/views/checklists.py

import json

from django.db.models import Count, Q, Prefetch
from django.http import HttpResponse, JsonResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST, require_http_methods
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count, Q

from .helpers import _actor_label, _log_card
from ..models import Card, Checklist, ChecklistItem


def _can_edit_board(request, board) -> bool:
    if not request.user.is_authenticated:
        return False
    if request.user.is_staff:
        return True

    memberships_qs = board.memberships.all()
    if memberships_qs.exists():
        return memberships_qs.filter(
            user=request.user,
            role__in=["owner", "editor"],
        ).exists()

    return bool(board.created_by_id == request.user.id)


def _card_checklists_qs(card: Card):
    return (
        card.checklists
        .annotate(
            total=Count("items"),
            done=Count("items", filter=Q(items__is_done=True)),
        )
        .prefetch_related(
            Prefetch(
                "items",
                queryset=ChecklistItem.objects.order_by("is_done", "position", "id"),
            )
        )
        .order_by("position", "created_at")
    )



# ==========================================================
# CHECKLISTS — REORDER (Drag and Drop) + AUDITORIA
# ==========================================================

@login_required
@require_POST
def checklists_reorder(request, card_id):
    card = get_object_or_404(Card, id=card_id, is_deleted=False)
    board = card.column.board

    if not _can_edit_board(request, board):
        return JsonResponse({"ok": False, "error": "Sem permissão."}, status=403)

    try:
        payload = json.loads(request.body.decode("utf-8"))
        order = payload.get("order", [])
        if not isinstance(order, list) or not order:
            return JsonResponse({"ok": False, "error": "order inválido"}, status=400)
        order = [int(x) for x in order]
    except Exception:
        return JsonResponse({"ok": False, "error": "JSON inválido"}, status=400)

    valid_ids = set(Checklist.objects.filter(card=card).values_list("id", flat=True))
    if set(order) != valid_ids:
        return JsonResponse({"ok": False, "error": "Checklist fora do card."}, status=400)

    with transaction.atomic():
        for idx, cid in enumerate(order):
            Checklist.objects.filter(id=cid, card=card).update(position=idx)

    actor = _actor_label(request)
    _log_card(card, request, f"<p><strong>{actor}</strong> reordenou checklists (drag).</p>")

    return JsonResponse({"ok": True})


@login_required
@require_POST
def checklist_items_reorder(request, card_id):
    card = get_object_or_404(Card, id=card_id, is_deleted=False)
    board = card.column.board

    if not _can_edit_board(request, board):
        return JsonResponse({"ok": False, "error": "Sem permissão."}, status=403)

    try:
        payload = json.loads(request.body.decode("utf-8"))
        updates = payload.get("updates", [])
        if not isinstance(updates, list) or not updates:
            return JsonResponse({"ok": False, "error": "updates inválido"}, status=400)
    except Exception:
        return JsonResponse({"ok": False, "error": "JSON inválido"}, status=400)

    checklist_ids = set()
    item_ids = set()

    for u in updates:
        try:
            checklist_ids.add(int(u.get("checklist_id")))
            item_ids.add(int(u.get("item_id")))
            int(u.get("position"))
        except Exception:
            return JsonResponse({"ok": False, "error": "Payload inválido (tipos)."}, status=400)

    valid_checklists = set(
        Checklist.objects.filter(card=card, id__in=checklist_ids).values_list("id", flat=True)
    )
    if checklist_ids - valid_checklists:
        return JsonResponse({"ok": False, "error": "Checklist fora do card."}, status=400)

    items = list(ChecklistItem.objects.filter(card=card, id__in=item_ids))
    items_map = {it.id: it for it in items}
    if set(item_ids) - set(items_map.keys()):
        return JsonResponse({"ok": False, "error": "Item fora do card."}, status=400)

    changed = []
    for u in updates:
        iid = int(u["item_id"])
        cid = int(u["checklist_id"])
        pos = int(u["position"])
        it = items_map[iid]

        if it.checklist_id != cid or it.position != pos:
            it.checklist_id = cid
            it.position = pos
            changed.append(it)

    with transaction.atomic():
        if changed:
            ChecklistItem.objects.bulk_update(changed, ["checklist_id", "position"])

    actor = _actor_label(request)
    _log_card(card, request, f"<p><strong>{actor}</strong> reordenou itens de checklist (drag).</p>")

    return JsonResponse({"ok": True})


# ==========================================================
# CHECKLISTS — CRUD + AUDITORIA
# ==========================================================

@login_required
@require_POST
def checklist_add(request, card_id):
    card = get_object_or_404(Card, id=card_id, is_deleted=False)
    board = card.column.board
    if not _can_edit_board(request, board):
        return HttpResponse("Sem permissão.", status=403)

    actor = _actor_label(request)
    title = (request.POST.get("title") or "").strip() or "Checklist"
    position = card.checklists.count()

    checklist = Checklist.objects.create(card=card, title=title, position=position)

    _log_card(card, request, f"<p><strong>{actor}</strong> criou a checklist <strong>{checklist.title}</strong>.</p>")
    return render(request, "boards/partials/checklist_list.html", {
    "checklists": _card_checklists_qs(card),
    "card": card,
})



@login_required
@require_POST
def checklist_rename(request, checklist_id):
    checklist = get_object_or_404(Checklist, id=checklist_id)
    card = checklist.card
    board = card.column.board
    if not _can_edit_board(request, board):
        return HttpResponse("Sem permissão.", status=403)

    actor = _actor_label(request)
    old_title = checklist.title
    title = (request.POST.get("title") or "").strip()
    if not title:
        return HttpResponse("Título inválido.", status=400)

    checklist.title = title
    checklist.save(update_fields=["title"])

    _log_card(card, request, f"<p><strong>{actor}</strong> renomeou a checklist de <strong>{old_title}</strong> para <strong>{title}</strong>.</p>")
    return render(request, "boards/partials/checklist_list.html", {
    "checklists": _card_checklists_qs(card),
    "card": card,
})




@login_required
@require_POST
def checklist_delete(request, checklist_id):
    checklist = get_object_or_404(Checklist, id=checklist_id)
    card = checklist.card
    board = card.column.board
    if not _can_edit_board(request, board):
        return HttpResponse("Sem permissão.", status=403)

    actor = _actor_label(request)
    title = checklist.title
    checklist.delete()

    for idx, c in enumerate(card.checklists.order_by("position", "created_at")):
        if c.position != idx:
            c.position = idx
            c.save(update_fields=["position"])

    _log_card(card, request, f"<p><strong>{actor}</strong> excluiu a checklist <strong>{title}</strong>.</p>")
    return render(request, "boards/partials/checklist_list.html", {
    "checklists": _card_checklists_qs(card),
    "card": card,
})




@login_required
@require_POST
def checklist_add_item(request, checklist_id):
    checklist = get_object_or_404(Checklist, id=checklist_id)
    card = checklist.card
    board = card.column.board
    if not _can_edit_board(request, board):
        return HttpResponse("Sem permissão.", status=403)

    actor = _actor_label(request)
    text = (request.POST.get("text") or "").strip()
    if not text:
        return HttpResponse("Texto vazio", status=400)

    position = checklist.items.count()
    item = ChecklistItem.objects.create(card=card, checklist=checklist, text=text, position=position)

    _log_card(card, request, f"<p><strong>{actor}</strong> adicionou item na checklist <strong>{checklist.title}</strong>: {item.text}.</p>")
    return render(request, "boards/partials/checklist_list.html", {
    "checklists": _card_checklists_qs(card),
    "card": card,
})




@login_required
@require_POST
def checklist_toggle_item(request, item_id):
    item = get_object_or_404(ChecklistItem, id=item_id)
    card = item.card
    board = card.column.board
    if not _can_edit_board(request, board):
        return HttpResponse("Sem permissão.", status=403)

    actor = _actor_label(request)

    item.is_done = not item.is_done
    item.save(update_fields=["is_done"])

    status = "concluiu" if item.is_done else "reabriu"
    _log_card(card, request, f"<p><strong>{actor}</strong> {status} um item da checklist: {item.text}.</p>")

    return render(request, "boards/partials/checklist_list.html", {
    "checklists": _card_checklists_qs(card),
    "card": card,
})




@login_required
@require_http_methods(["POST"])
def checklist_delete_item(request, item_id):
    item = get_object_or_404(ChecklistItem, id=item_id)
    card = item.card
    board = card.column.board
    if not _can_edit_board(request, board):
        return HttpResponse("Sem permissão.", status=403)

    actor = _actor_label(request)
    text = item.text
    checklist = item.checklist
    item.delete()

    if checklist:
        for idx, it in enumerate(checklist.items.order_by("position", "created_at")):
            if it.position != idx:
                it.position = idx
                it.save(update_fields=["position"])

    _log_card(card, request, f"<p><strong>{actor}</strong> excluiu um item da checklist: {text}.</p>")
    return render(request, "boards/partials/checklist_list.html", {
    "checklists": _card_checklists_qs(card),
    "card": card,
})




@login_required
@require_POST
def checklist_update_item(request, item_id):
    item = get_object_or_404(ChecklistItem, id=item_id)
    card = item.card
    board = card.column.board
    if not _can_edit_board(request, board):
        return HttpResponse("Sem permissão.", status=403)

    actor = _actor_label(request)
    old = item.text
    text = (request.POST.get("text") or "").strip()
    if not text:
        return HttpResponse("Texto vazio", status=400)

    item.text = text
    item.save(update_fields=["text"])

    _log_card(card, request, f"<p><strong>{actor}</strong> editou um item da checklist de {old} para {text}.</p>")
    return render(request, "boards/partials/checklist_list.html", {
    "checklists": _card_checklists_qs(card),
    "card": card,
})




# ==========================================================
# CHECKLISTS — COMPAT/LEGADO (rotas antigas)
# ==========================================================

@login_required
@require_POST
def checklist_move(request, checklist_id):
    checklist = get_object_or_404(Checklist, id=checklist_id)
    card = checklist.card
    board = card.column.board

    if not _can_edit_board(request, board):
        return HttpResponse("Sem permissão.", status=403)

    direction = (request.POST.get("direction") or "").strip().lower()
    new_position_raw = (request.POST.get("position") or request.POST.get("new_position") or "").strip()

    checklists = list(card.checklists.order_by("position", "created_at"))
    if not checklists:
        return render(request, "boards/partials/checklist_list.html", {
    "checklists": _card_checklists_qs(card),
    "card": card,
})



    try:
        current_index = next(i for i, c in enumerate(checklists) if c.id == checklist.id)
    except StopIteration:
        return HttpResponseBadRequest("Checklist inválido.")

    if new_position_raw:
        try:
            pos = int(new_position_raw)
            if 1 <= pos <= len(checklists):
                new_index = pos - 1
            else:
                new_index = pos
        except Exception:
            return HttpResponseBadRequest("position inválido.")
    elif direction in ("up", "down"):
        new_index = current_index - 1 if direction == "up" else current_index + 1
    else:
        return HttpResponseBadRequest("Informe 'direction' (up/down) ou 'position'.")

    new_index = max(0, min(len(checklists) - 1, new_index))
    if new_index != current_index:
        moved = checklists.pop(current_index)
        checklists.insert(new_index, moved)

        with transaction.atomic():
            for idx, c in enumerate(checklists):
                if c.position != idx:
                    c.position = idx
                    c.save(update_fields=["position"])

        actor = _actor_label(request)
        _log_card(card, request, f"<p><strong>{actor}</strong> reordenou checklists (legado).</p>")

    return render(request, "boards/partials/checklist_list.html", {
    "checklists": _card_checklists_qs(card),
    "card": card,
})




@login_required
@require_POST
def checklist_move_up(request, item_id):
    return _checklist_move_item_delta(request, item_id, delta=-1)


@login_required
@require_POST
def checklist_move_down(request, item_id):
    return _checklist_move_item_delta(request, item_id, delta=+1)


def _checklist_move_item_delta(request, item_id, delta: int):
    item = get_object_or_404(ChecklistItem, id=item_id)
    card = item.card
    board = card.column.board

    if not _can_edit_board(request, board):
        return HttpResponse("Sem permissão.", status=403)

    if not item.checklist_id:
        return HttpResponseBadRequest("Item não está associado a um checklist.")

    items = list(
        ChecklistItem.objects.filter(checklist_id=item.checklist_id).order_by("position", "created_at")
    )

    try:
        idx = next(i for i, it in enumerate(items) if it.id == item.id)
    except StopIteration:
        return HttpResponseBadRequest("Item inválido.")

    new_idx = idx + delta
    if new_idx < 0 or new_idx >= len(items):
        return render(request, "boards/partials/checklist_list.html", {
    "checklists": _card_checklists_qs(card),
    "card": card,
})



    a = items[idx]
    b = items[new_idx]

    with transaction.atomic():
        a_pos = a.position
        b_pos = b.position
        a.position = b_pos
        b.position = a_pos
        a.save(update_fields=["position"])
        b.save(update_fields=["position"])

    actor = _actor_label(request)
    _log_card(card, request, f"<p><strong>{actor}</strong> reordenou item de checklist (legado).</p>")

    return render(request, "boards/partials/checklist_list.html", {
    "checklists": _card_checklists_qs(card),
    "card": card,
})
#END boards/views/checklists.py
