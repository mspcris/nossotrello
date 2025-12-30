# boards/views/modal_card_term.py

import json
import re
from datetime import date, timedelta

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils.html import escape
from django.views.decorators.http import require_POST

from boards.models import Card
from .helpers import _actor_label, _log_card, _card_modal_context
from .cards import _user_can_edit_board, _deny_read_only


# ============================================================================
# LEGADO (seu "term" como tags) — mantido
# ============================================================================

@login_required
@require_POST
def remove_term(request, card_id):
    """
    Remove um termo do card (mantém os demais).
    Retorna HTML do modal atualizado.
    """
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

    return render(request, "boards/partials/card_modal_body.html", _card_modal_context(card))


@login_required
@require_POST
def set_term_color(request, card_id):
    """
    LEGADO: Salva/atualiza cor do "termo" (tag_colors_json) e devolve JSON.
    """
    card = get_object_or_404(Card, id=card_id, is_deleted=False)
    board = card.column.board

    if not _user_can_edit_board(request.user, board):
        return _deny_read_only(request, as_json=True)

    term = (request.POST.get("term") or "").strip()
    color = (request.POST.get("color") or "").strip()
    if not term or not color:
        return JsonResponse({"error": "Dados inválidos."}, status=400)

    if not re.match(r"^#[0-9a-fA-F]{6}$", color):
        return JsonResponse({"error": "Cor inválida."}, status=400)

    raw = card.tag_colors_json or "{}"
    try:
        data = json.loads(raw) if raw else {}
    except Exception:
        data = {}

    data[term] = color
    card.tag_colors_json = json.dumps(data, ensure_ascii=False)
    card.save(update_fields=["tag_colors_json"])

    board.version += 1
    board.save(update_fields=["version"])

    terms_bar_html = render(
        request,
        "boards/partials/card_terms_bar.html",
        {"card": card, "term_colors": data},
    ).content.decode("utf-8")

    modal_html = render(
        request,
        "boards/partials/card_modal_body.html",
        _card_modal_context(card),
    ).content.decode("utf-8")

    return JsonResponse({"ok": True, "terms_bar": terms_bar_html, "modal": modal_html})


# ============================================================================
# NOVO PROCESSO — TERM PRAZOS (term_due_date / term_warn_date / term_notify)
# ============================================================================

def _parse_ymd(s: str):
    s = (s or "").strip()
    if not s:
        return None
    try:
        y, m, d = [int(x) for x in s.split("-", 2)]
        return date(y, m, d)
    except Exception:
        return None


def _default_warn(due: date) -> date:
    return due - timedelta(days=5)


@login_required
@require_POST
def set_card_term_due(request, card_id):
    """
    Salva term_due_date / term_warn_date / term_notify no Card.
    Regras:
    - term_due_date vazio => limpa warn e não aplica status
    - term_due_date preenchido => term_warn_date obrigatório (default = due-5 se vier vazio)
    - term_notify default True; se False, não mostra badge/cor (frontend)
    Retorna modal atualizado (HTML) para swap.
    """
    card = get_object_or_404(Card, id=card_id, is_deleted=False)
    board = card.column.board

    if not _user_can_edit_board(request.user, board):
        return _deny_read_only(request, as_json=True)

    due_raw = request.POST.get("term_due_date")
    warn_raw = request.POST.get("term_warn_date")
    notify_raw = request.POST.get("term_notify")

    due = _parse_ymd(due_raw)
    warn = _parse_ymd(warn_raw)

    # checkbox: vem "on" ou "1"
    notify = True
    if notify_raw is None:
        # se input não veio, mantém padrão True (ou valor atual se existir)
        notify = bool(getattr(card, "term_notify", True))
    else:
        notify = str(notify_raw).lower() in ("1", "true", "on", "yes")

    updates = []

    if not due:
        # sem prazo => zera warn também
        if getattr(card, "term_due_date", None) is not None:
            card.term_due_date = None
            updates.append("term_due_date")
        if getattr(card, "term_warn_date", None) is not None:
            card.term_warn_date = None
            updates.append("term_warn_date")
    else:
        # com prazo => warn obrigatório
        if not warn:
            warn = _default_warn(due)

        if getattr(card, "term_due_date", None) != due:
            card.term_due_date = due
            updates.append("term_due_date")
        if getattr(card, "term_warn_date", None) != warn:
            card.term_warn_date = warn
            updates.append("term_warn_date")

    if getattr(card, "term_notify", True) != notify:
        card.term_notify = notify
        updates.append("term_notify")

    if not updates:
        # nada mudou, só re-render
        return render(request, "boards/partials/card_modal_body.html", _card_modal_context(card))

    card.save(update_fields=updates)

    # bump version para polling/refresh do board
    board.version += 1
    board.save(update_fields=["version"])

    # log simples (somente quando set/clear)
    actor = _actor_label(request)
    if not due:
        _log_card(card, request, f"<p><strong>{actor}</strong> removeu o prazo (term).</p>")
    else:
        _log_card(
            card,
            request,
            f"<p><strong>{actor}</strong> definiu prazo (term): "
            f"<strong>{escape(str(card.term_due_date))}</strong> "
            f"(aviso: <strong>{escape(str(card.term_warn_date))}</strong>).</p>",
        )

    return render(request, "boards/partials/card_modal_body.html", _card_modal_context(card))


@login_required
@require_POST
def set_board_term_colors(request, board_id):
    """
    Salva cores do term no Board (3 estados: ok/warn/overdue).
    Espera POST:
      term_color_ok, term_color_warn, term_color_overdue
    Retorna JSON com term_colors.
    """
    # board via card.column.board é comum, mas aqui é direto por id
    from boards.models import Board  # import local para evitar circular

    board = get_object_or_404(Board, id=board_id, is_deleted=False) if hasattr(Board, "is_deleted") else get_object_or_404(Board, id=board_id)

    if not _user_can_edit_board(request.user, board):
        return _deny_read_only(request, as_json=True)

    c_ok = (request.POST.get("term_color_ok") or "").strip()
    c_warn = (request.POST.get("term_color_warn") or "").strip()
    c_over = (request.POST.get("term_color_overdue") or "").strip()

    def valid_hex(c):
        return bool(re.match(r"^#[0-9a-fA-F]{6}$", c or ""))

    if not (valid_hex(c_ok) and valid_hex(c_warn) and valid_hex(c_over)):
        return JsonResponse({"ok": False, "error": "Cores inválidas."}, status=400)

    # guarda em JSON no board
    colors = {"ok": c_ok, "warn": c_warn, "overdue": c_over}

    # suporte a diferentes implementações (term_colors / term_colors_json)
    if hasattr(board, "term_colors"):
        board.term_colors = colors
        board.save(update_fields=["term_colors"])
    elif hasattr(board, "term_colors_json"):
        board.term_colors_json = json.dumps(colors, ensure_ascii=False)
        board.save(update_fields=["term_colors_json"])
    else:
        return JsonResponse({"ok": False, "error": "Board sem campo term_colors."}, status=500)

    board.version += 1
    board.save(update_fields=["version"])

    return JsonResponse({"ok": True, "term_colors": colors})
# END boards/views/modal_card_term.py
