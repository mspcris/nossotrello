# boards/views/search.py
from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.db.models import Q, Prefetch
from django.http import JsonResponse
from django.views.decorators.http import require_GET

from ..models import (
    Board,
    BoardMembership,
    Card,
    CardAttachment,
    Checklist,
    ChecklistItem,
    CardLog,
)


def _make_excerpt(text: str, q: str, max_len: int = 180, around: int = 70) -> str:
    if not text:
        return ""

    t = str(text).strip()
    if not t:
        return ""

    ql = q.lower()
    tl = t.lower()
    i = tl.find(ql)

    if i < 0:
        return (t[: max_len - 1] + "…") if len(t) > max_len else t

    start = max(0, i - around)
    end = min(len(t), i + len(q) + around)

    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(t) else ""
    chunk = t[start:end].strip()

    if len(chunk) > max_len:
        chunk = chunk[: max_len - 1] + "…"

    return f"{prefix}{chunk}{suffix}"


def _best_card_match(card: Card, q: str) -> tuple[str, str]:
    ql = q.lower()

    if (card.title or "").lower().find(ql) >= 0:
        return "title", _make_excerpt(card.title or "", q)

    if (card.description or "").lower().find(ql) >= 0:
        return "description", _make_excerpt(card.description or "", q)

    if (card.tags or "").lower().find(ql) >= 0:
        return "tags", _make_excerpt(card.tags or "", q)

    # attachments (nome/descrição)
    # (prefetch normal: card.attachments.all())
    try:
        atts = list(card.attachments.all())
    except Exception:
        atts = []

    for a in atts:
        fname = ""
        for attr in ("file", "attachment", "arquivo", "upload"):
            try:
                f = getattr(a, attr, None)
                if f and getattr(f, "name", ""):
                    fname = (f.name or "").split("/")[-1]
                    break
            except Exception:
                pass

        if fname and fname.lower().find(ql) >= 0:
            return "attachment", _make_excerpt(fname, q)

        if (getattr(a, "description", "") or "").lower().find(ql) >= 0:
            return "attachment", _make_excerpt(getattr(a, "description", "") or "", q)

    for ch in getattr(card, "_pref_checklists", []) or []:
        if (ch.title or "").lower().find(ql) >= 0:
            return "checklist", _make_excerpt(ch.title or "", q)

    for it in getattr(card, "_pref_checklist_items", []) or []:
        if (it.text or "").lower().find(ql) >= 0:
            return "checklist_item", _make_excerpt(it.text or "", q)

    for lg in getattr(card, "_pref_logs", []) or []:
        if (lg.content or "").lower().find(ql) >= 0:
            return "activity", _make_excerpt(lg.content or "", q)

    return "card", _make_excerpt(card.description or card.title or "", q)


@login_required
@require_GET
def board_search(request, board_id: int):
    q_raw = (request.GET.get("q") or "").strip()
    if not q_raw:
        return JsonResponse({"card_ids": [], "column_ids": []})

    board = Board.objects.filter(id=board_id, is_deleted=False).only("id").first()
    if not board:
        return JsonResponse({"card_ids": [], "column_ids": []}, status=404)

    has_access = BoardMembership.objects.filter(board_id=board_id, user=request.user).exists()
    if not has_access:
        return JsonResponse({"card_ids": [], "column_ids": []}, status=403)

    q = q_raw

    qs = (
        Card.objects
        .filter(column__board_id=board_id, column__is_deleted=False, is_deleted=False)
        .select_related("column")
        .filter(
            Q(title__icontains=q) |
            Q(description__icontains=q) |
            Q(tags__icontains=q) |
            Q(logs__content__icontains=q) |
            Q(checklists__title__icontains=q) |
            Q(checklist_items__text__icontains=q) |
            Q(attachments__description__icontains=q)
        )
        .distinct()
        .only("id", "column_id")
    )

    card_ids = list(qs.values_list("id", flat=True))
    column_ids = sorted(set(qs.values_list("column_id", flat=True)))

    return JsonResponse({"card_ids": card_ids, "column_ids": column_ids})


@login_required
@require_GET
def home_search(request):
    q_raw = (request.GET.get("q") or "").strip()
    if not q_raw:
        return JsonResponse({"cards": [], "boards": []})

    q = q_raw

    boards_qs = (
        Board.objects
        .filter(is_deleted=False, memberships__user=request.user)
        .distinct()
        .only("id", "name")
        .order_by("name")
    )

    attachments_pf = Prefetch(
        "attachments",
        queryset=CardAttachment.objects.only("id", "card_id", "description", "file"),
    )
    checklists_pf = Prefetch(
        "checklists",
        queryset=Checklist.objects.only("id", "card_id", "title"),
        to_attr="_pref_checklists",
    )
    checklist_items_pf = Prefetch(
        "checklist_items",
        queryset=ChecklistItem.objects.only("id", "card_id", "text"),
        to_attr="_pref_checklist_items",
    )
    logs_pf = Prefetch(
        "logs",
        queryset=CardLog.objects.only("id", "card_id", "content").order_by("-created_at"),
        to_attr="_pref_logs",
    )

    cards_qs = (
        Card.objects
        .filter(
            is_deleted=False,
            column__is_deleted=False,
            column__board__is_deleted=False,
            column__board__memberships__user=request.user,
        )
        .select_related("column", "column__board")
        .prefetch_related(attachments_pf, checklists_pf, checklist_items_pf, logs_pf)
        .filter(
            Q(title__icontains=q) |
            Q(description__icontains=q) |
            Q(tags__icontains=q) |
            Q(logs__content__icontains=q) |
            Q(checklists__title__icontains=q) |
            Q(checklist_items__text__icontains=q) |
            Q(attachments__description__icontains=q)
        )
        .distinct()
        .only(
            "id", "title", "description", "tags",
            "column_id", "column__name",          # <<<<<<<<<<
            "column__board_id", "column__board__name",
        )
        .order_by("-id")[:40]
    )

    cards_payload = []
    for c in cards_qs:
        match_in, excerpt = _best_card_match(c, q)

        cards_payload.append({
            "id": c.id,
            "title": c.title or "(sem título)",
            "board_id": c.column.board_id,
            "board_name": c.column.board.name or "",
            "column_id": c.column_id,
            "column_title": c.column.name or "",  # mantém a chave pro seu JS
            "match_in": match_in,
            "excerpt": excerpt,
        })

    boards_payload = [{"id": b.id, "name": b.name} for b in boards_qs.filter(name__icontains=q)[:20]]

    return JsonResponse({"cards": cards_payload, "boards": boards_payload})
