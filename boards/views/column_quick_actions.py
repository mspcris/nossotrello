# boards/views/column_quick_actions.py
"""Ações rápidas da coluna (PT2-T4U-ALPP): botões no card que o movem para
outra coluna sem abri-lo. Modal de configuração por coluna (quem edita o quadro)."""
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render

from ..models import Column
from ..permissions import can_edit_board


def _render(request, column, msg=None):
    destinos = list(Column.objects.filter(board_id=column.board_id, is_deleted=False)
                    .exclude(id=column.id).order_by("position", "id"))
    nomes = {c.id: c.name for c in destinos}
    acoes = []
    for a in (column.quick_actions or []):
        if not (isinstance(a, dict) and a.get("to")):
            continue
        to = int(a["to"])
        acoes.append({"to": to, "label": a.get("label") or nomes.get(to, ""),
                      "destino": nomes.get(to), "viva": to in nomes})
    return render(request, "boards/partials/column_quick_actions_modal.html", {
        "column": column, "destinos": destinos, "acoes": acoes, "msg": msg,
    })


@login_required
def column_quick_actions_config(request, column_id):
    column = get_object_or_404(Column, id=column_id, is_deleted=False)
    if not can_edit_board(request.user, column.board):
        return HttpResponse("Sem permissão.", status=403)
    msg = None
    if request.method == "POST":
        acao = (request.POST.get("acao") or "add").strip()
        atuais = [a for a in (column.quick_actions or []) if isinstance(a, dict) and a.get("to")]
        if acao == "remove":
            try:
                alvo = int(request.POST.get("to") or 0)
            except ValueError:
                alvo = 0
            atuais = [a for a in atuais if int(a["to"]) != alvo]
            msg = "Ação removida."
        else:
            try:
                to = int(request.POST.get("to") or 0)
            except ValueError:
                to = 0
            destino = (Column.objects.filter(id=to, board_id=column.board_id, is_deleted=False)
                       .exclude(id=column.id).first())
            if not destino:
                msg = "Escolha a coluna de destino."
            elif any(int(a["to"]) == to for a in atuais):
                msg = "Já existe uma ação para essa coluna."
            elif len(atuais) >= 6:
                msg = "No máximo 6 ações rápidas por coluna — o card precisa caber."
            else:
                label = (request.POST.get("label") or "").strip()[:40] or destino.name[:40]
                atuais.append({"to": to, "label": label})
                msg = "Ação adicionada. ✅"
        column.quick_actions = atuais
        column.save(update_fields=["quick_actions"])
        try:
            column.board.version = (column.board.version or 0) + 1
            column.board.save(update_fields=["version"])
        except Exception:
            pass
    return _render(request, column, msg)
