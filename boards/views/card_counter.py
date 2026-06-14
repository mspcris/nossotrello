"""Card contador: modal de criação + criar o card especial na coluna."""
from django.contrib.auth.decorators import login_required
from django.db.models import F
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.template.loader import render_to_string
from django.views.decorators.http import require_http_methods

from ..models import Card, Column
from ..permissions import can_edit_board
from ..services.card_counters import default_title_for


def _render(request, column, msg=None):
    return render(request, "boards/partials/card_counter_modal.html", {
        "column": column,
        "mode_choices": Card.COUNTER_MODE_CHOICES,
        "msg": msg,
    })


@login_required
@require_http_methods(["GET", "POST"])
def card_counter_modal(request, column_id):
    column = get_object_or_404(Column, id=column_id, is_deleted=False)
    if not can_edit_board(request.user, column.board):
        return HttpResponse("Sem permissão.", status=403)

    if request.method == "POST":
        mode = request.POST.get("mode")
        if mode in dict(Card.COUNTER_MODE_CHOICES):
            try:
                days = max(1, min(3650, int(request.POST.get("days") or 15)))
            except Exception:
                days = 15
            title = (request.POST.get("title") or "").strip() or default_title_for(mode, days)
            color = (request.POST.get("cover_color") or "").strip()
            # empurra os demais cards p/ baixo e fixa o contador no topo
            Card.objects.filter(column=column).update(position=F("position") + 1)
            card = Card.all_objects.create(
                column=column,
                created_by=request.user,
                title=title[:255],
                counter_mode=mode,
                counter_days=days,
                cover_color=color[:9] if color.startswith("#") else "",
                position=0,
            )
            board = column.board
            board.version = (board.version or 0) + 1
            board.save(update_fields=["version"])

            # insere o card na coluna NA HORA (OOB) — o realtime fica pausado com
            # o modal aberto, então sem isso o número só aparecia após F5.
            resp = _render(request, column, msg="Card contador criado no topo da lista. ✅")
            card_html = render_to_string("boards/partials/card_item.html", {"card": card}, request=request)
            oob = f'<div hx-swap-oob="afterbegin:#cards-col-{column.id}">{card_html}</div>'
            resp.content = resp.content + oob.encode("utf-8")
            return resp

    return _render(request, column)
