# boards/views/modal_card_term.py

import json
import re
from datetime import date, timedelta

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils.html import escape
from django.views.decorators.http import require_POST
from django.template.loader import render_to_string

from boards.models import Card
from .helpers import _actor_label, _log_card, _card_modal_context
from .cards import _user_can_edit_board, _deny_read_only


# ============================================================================
# LEGADO — termos como tags
# ============================================================================

@login_required
@require_POST
def remove_term(request, card_id):
    card = get_object_or_404(Card, id=card_id, is_deleted=False)
    board = card.column.board

    if not _user_can_edit_board(request.user, board):
        return _deny_read_only(request, as_json=True)

    term = (request.POST.get("term") or "").strip()
    if not term:
        return HttpResponse("Termo inválido.", status=400)

    terms = [t.strip() for t in (card.tags or "").split(",") if t.strip()]
    before = list(terms)
    terms = [t for t in terms if t != term]
    card.tags = ", ".join(terms)
    card.save(update_fields=["tags"])

    board.version += 1
    board.save(update_fields=["version"])

    if before != terms:
        actor = _actor_label(request)
        _log_card(
            card,
            request,
            f"<p><strong>{actor}</strong> removeu o termo <strong>{escape(term)}</strong>.</p>",
        )

    return render(
        request,
        "boards/partials/card_modal_body.html",
        _card_modal_context(card),
    )


@login_required
@require_POST
def set_term_color(request, card_id):
    card = get_object_or_404(Card, id=card_id, is_deleted=False)
    board = card.column.board

    if not _user_can_edit_board(request.user, board):
        return _deny_read_only(request, as_json=True)

    term = (request.POST.get("term") or "").strip()
    color = (request.POST.get("color") or "").strip()

    if not term or not re.match(r"^#[0-9a-fA-F]{6}$", color):
        return JsonResponse({"error": "Dados inválidos."}, status=400)

    try:
        data = json.loads(card.tag_colors_json or "{}")
    except Exception:
        data = {}

    data[term] = color
    card.tag_colors_json = json.dumps(data, ensure_ascii=False)
    card.save(update_fields=["tag_colors_json"])

    board.version += 1
    board.save(update_fields=["version"])

    return JsonResponse({
        "ok": True,
        "modal": render_to_string(
            "boards/partials/card_modal_body.html",
            _card_modal_context(card),
            request=request,
        ),
    })


# ============================================================================
# NOVO PROCESSO — PRAZOS (term)
# ============================================================================

def _parse_ymd(s: str):
    try:
        y, m, d = map(int, (s or "").split("-"))
        return date(y, m, d)
    except Exception:
        return None


def _default_warn(due: date) -> date:
    return due - timedelta(days=5)


@login_required
@require_POST
def set_card_term_due(request, card_id):
    card = get_object_or_404(Card, id=card_id, is_deleted=False)
    board = card.column.board

    if not _user_can_edit_board(request.user, board):
        return _deny_read_only(request, as_json=True)

    due = _parse_ymd(request.POST.get("term_due_date"))
    warn = _parse_ymd(request.POST.get("term_warn_date"))
    notify = str(request.POST.get("term_notify", "1")).lower() in ("1", "true", "on", "yes")

    updates = []

    if not due:
        if card.term_due_date:
            card.term_due_date = None
            updates.append("term_due_date")
        if card.term_warn_date:
            card.term_warn_date = None
            updates.append("term_warn_date")
    else:
        if not warn:
            warn = _default_warn(due)
        if card.term_due_date != due:
            card.term_due_date = due
            updates.append("term_due_date")
        if card.term_warn_date != warn:
            card.term_warn_date = warn
            updates.append("term_warn_date")

    if card.term_notify != notify:
        card.term_notify = notify
        updates.append("term_notify")

    if updates:
        card.save(update_fields=updates)
        board.version += 1
        board.save(update_fields=["version"])

        actor = _actor_label(request)
        if due:
            _log_card(
                card,
                request,
                f"<p><strong>{actor}</strong> definiu prazo: "
                f"<strong>{escape(str(card.term_due_date))}</strong> "
                f"(aviso: <strong>{escape(str(card.term_warn_date))}</strong>).</p>",
            )
        else:
            _log_card(card, request, f"<p><strong>{actor}</strong> removeu o prazo.</p>")

    return JsonResponse({
        "ok": True,
        "card_id": card.id,
        "modal": render_to_string(
            "boards/partials/card_modal_body.html",
            _card_modal_context(card),
            request=request,
        ),
        "snippet": render_to_string(
            "boards/partials/card_item.html",
            {"card": card},
            request=request,
        ),
    })


# ============================================================================
# CORES DE PRAZO NO BOARD
# ============================================================================

@login_required
@require_POST
def set_board_term_colors(request, board_id):
    from boards.models import Board

    board = get_object_or_404(Board, id=board_id)

    if not _user_can_edit_board(request.user, board):
        return _deny_read_only(request, as_json=True)

    colors = {
        "ok": request.POST.get("term_color_ok"),
        "warn": request.POST.get("term_color_warn"),
        "overdue": request.POST.get("term_color_overdue"),
    }

    if not all(re.match(r"^#[0-9a-fA-F]{6}$", c or "") for c in colors.values()):
        return JsonResponse({"ok": False, "error": "Cores inválidas."}, status=400)

    if hasattr(board, "term_colors"):
        board.term_colors = colors
        board.save(update_fields=["term_colors"])
    else:
        board.term_colors_json = json.dumps(colors, ensure_ascii=False)
        board.save(update_fields=["term_colors_json"])

    board.version += 1
    board.save(update_fields=["version"])

    return JsonResponse({"ok": True, "term_colors": colors})
