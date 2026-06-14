# boards/views/column_autosort.py
"""Auto-ordenação agendada da coluna: modal de config + 'ordenar agora'."""
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from ..models import Column
from ..permissions import can_edit_board
from ..services.column_autosort import apply_autosort


def _render(request, column, msg=None):
    return render(request, "boards/partials/column_autosort_modal.html", {
        "column": column,
        "freq_choices": Column.AUTOSORT_FREQ_CHOICES,
        "field_choices": Column.AUTOSORT_FIELD_CHOICES,
        "weekdays": [(0, "Segunda"), (1, "Terça"), (2, "Quarta"), (3, "Quinta"),
                     (4, "Sexta"), (5, "Sábado"), (6, "Domingo")],
        "msg": msg,
    })


@login_required
def column_autosort_config(request, column_id):
    column = get_object_or_404(Column, id=column_id, is_deleted=False)
    if not can_edit_board(request.user, column.board):
        return HttpResponse("Sem permissão.", status=403)

    msg = None
    if request.method == "POST":
        freq = request.POST.get("autosort_freq")
        if freq in dict(Column.AUTOSORT_FREQ_CHOICES):
            column.autosort_freq = freq
        if request.POST.get("autosort_field") in dict(Column.AUTOSORT_FIELD_CHOICES):
            column.autosort_field = request.POST.get("autosort_field")
        column.autosort_dir = "desc" if request.POST.get("autosort_dir") == "desc" else "asc"
        try:
            column.autosort_weekday = max(0, min(6, int(request.POST.get("autosort_weekday") or 0)))
        except Exception:
            column.autosort_weekday = 0
        column.save(update_fields=["autosort_freq", "autosort_field", "autosort_dir", "autosort_weekday"])
        msg = "Configuração salva. ✅"

    return _render(request, column, msg)


@login_required
@require_http_methods(["POST"])
def column_autosort_now(request, column_id):
    column = get_object_or_404(Column, id=column_id, is_deleted=False)
    if not can_edit_board(request.user, column.board):
        return HttpResponse("Sem permissão.", status=403)
    changed = apply_autosort(column)
    column.autosort_last_run = timezone.localdate()
    column.save(update_fields=["autosort_last_run"])
    return HttpResponse(
        f'<div class="ei-result ei-result--ok">Ordenado agora: {changed} card(s) reposicionado(s). ✅</div>'
    )
