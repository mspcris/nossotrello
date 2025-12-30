# boards/views/modal_tag.py

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
def remove_tag(request, card_id):
    """
    Remove uma etiqueta do card (mantém as demais).
    Retorna HTML do modal atualizado.
    """
    card = get_object_or_404(Card, id=card_id, is_deleted=False)
    board = card.column.board

    # escrita bloqueada para VIEWER
    if not _user_can_edit_board(request.user, board):
        return _deny_read_only(request, as_json=True)

    tag = (request.POST.get("tag") or "").strip()
    if not tag:
        return HttpResponse("Tag inválida.", status=400)

    tags = [t.strip() for t in (card.tags or "").split(",") if t.strip()]
    before = list(tags)
    tags = [t for t in tags if t != tag]
    card.tags = ", ".join(tags)
    card.save(update_fields=["tags"])

    # version do board (polling/refresh)
    board.version += 1
    board.save(update_fields=["version"])

    # log (só se realmente removeu)
    if before != tags:
        actor = _actor_label(request)
        _log_card(
            card,
            request,
            f"<p><strong>{actor}</strong> removeu a etiqueta <strong>{escape(tag)}</strong>.</p>",
        )

    return render(request, "boards/partials/card_modal_body.html", _card_modal_context(card))


@login_required
@require_POST
def set_tag_color(request, card_id):
    """
    Salva/atualiza cor da etiqueta (tag_colors_json) e devolve
    (a) barra de tags (parcial) e (b) HTML do modal atualizado.
    """
    card = get_object_or_404(Card, id=card_id, is_deleted=False)
    board = card.column.board

    # escrita bloqueada para VIEWER
    if not _user_can_edit_board(request.user, board):
        return _deny_read_only(request, as_json=True)

    tag = (request.POST.get("tag") or "").strip()
    color = (request.POST.get("color") or "").strip()
    if not tag or not color:
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

    data[tag] = color
    card.tag_colors_json = json.dumps(data, ensure_ascii=False)
    card.save(update_fields=["tag_colors_json"])

    # version do board (polling/refresh)
    board.version += 1
    board.save(update_fields=["version"])

    # barra de tags no modal (parcial)
    tags_bar_html = render(
        request,
        "boards/partials/card_tags_bar.html",
        {
            "card": card,
            "tag_colors": data,
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
            "tags_bar": tags_bar_html,
            "modal": modal_html,
        }
    )
#END boards/views/modal_tag.py