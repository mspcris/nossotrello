# boards/views/modal_card_term.py

import json
import re

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils.html import escape
from django.views.decorators.http import require_POST

from boards.models import Card
from .helpers import _actor_label, _log_card, _card_modal_context
from .cards import _user_can_edit_board, _deny_read_only


@login_required
@require_POST
def remove_term(request, card_id):
    """
    Remove um termo do card (mantém os demais).
    Retorna HTML do modal atualizado.
    """
    card = get_object_or_404(Card, id=card_id, is_deleted=False)
    board = card.column.board

    # escrita bloqueada para VIEWER
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

    # version do board (polling/refresh)
    board.version += 1
    board.save(update_fields=["version"])

    # log (só se realmente removeu)
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
    Salva/atualiza cor do termo (tag_colors_json) e devolve:
    (a) barra de termos (parcial novo) e (b) HTML do modal atualizado.
    """
    card = get_object_or_404(Card, id=card_id, is_deleted=False)
    board = card.column.board

    # escrita bloqueada para VIEWER
    if not _user_can_edit_board(request.user, board):
        return _deny_read_only(request, as_json=True)

    term = (request.POST.get("term") or "").strip()
    color = (request.POST.get("color") or "").strip()
    if not term or not color:
        return JsonResponse({"error": "Dados inválidos."}, status=400)

    # validação simples do formato (mantém compat com o frontend)
    if not re.match(r"^#[0-9a-fA-F]{6}$", color):
        return JsonResponse({"error": "Cor inválida."}, status=400)

    # carrega json existente
    raw = card.tag_colors_json or "{}"
    try:
        data = json.loads(raw) if raw else {}
    except Exception:
        data = {}

    data[term] = color
    card.tag_colors_json = json.dumps(data, ensure_ascii=False)
    card.save(update_fields=["tag_colors_json"])

    # version do board (polling/refresh)
    board.version += 1
    board.save(update_fields=["version"])

    # barra de termos no modal (parcial novo)
    terms_bar_html = render(
        request,
        "boards/partials/card_terms_bar.html",
        {
            "card": card,
            "term_colors": data,  # (mantém semântica “term”, mesmo que o template use tag_color hoje)
        },
    ).content.decode("utf-8")

    # modal completo atualizado
    modal_html = render(
        request,
        "boards/partials/card_modal_body.html",
        _card_modal_context(card),
    ).content.decode("utf-8")

    return JsonResponse(
        {
            "ok": True,
            "terms_bar": terms_bar_html,
            "modal": modal_html,
        }
    )
# END boards/views/modal_card_term.py
