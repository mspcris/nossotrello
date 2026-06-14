# boards/views/column_automation.py
"""Automação da coluna: modal (listar + adicionar) e remover regra."""
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_http_methods

from ..models import BoardMembership, Column, ColumnAutomation
from ..permissions import can_edit_board


def _render_modal(request, column):
    members = (
        BoardMembership.objects.filter(board=column.board)
        .select_related("user").order_by("user__email")
    )
    return render(request, "boards/partials/column_automation_modal.html", {
        "column": column,
        "rules": column.automations.all(),
        "other_columns": column.board.columns.filter(is_deleted=False)
                               .exclude(id=column.id).order_by("position"),
        "members": members,
        "trigger_choices": ColumnAutomation.TRIGGER_CHOICES,
        "action_choices": ColumnAutomation.ACTION_CHOICES,
    })


@login_required
def column_automation_modal(request, column_id):
    column = get_object_or_404(Column, id=column_id, is_deleted=False)
    if not can_edit_board(request.user, column.board):
        return HttpResponse("Sem permissão.", status=403)

    if request.method == "POST":
        trigger = request.POST.get("trigger")
        action = request.POST.get("action")
        if trigger in dict(ColumnAutomation.TRIGGER_CHOICES) and action in dict(ColumnAutomation.ACTION_CHOICES):
            params = {}
            # limiar de contagem (gatilhos count_below / count_above)
            if trigger in ("count_below", "count_above"):
                try:
                    params["count"] = int(request.POST.get("count") or 0)
                except Exception:
                    params["count"] = 0
            if action == "send_email":
                params["email"] = (request.POST.get("email") or "").strip()
                msg = (request.POST.get("message") or "").strip()
                if msg:
                    params["message"] = msg[:2000]
            elif action == "assign_user":
                params["user_id"] = request.POST.get("user_id")
            elif action in ("move_to", "copy_to"):
                params["target_column_id"] = request.POST.get("target_column_id")
            elif action in ("set_due", "set_start"):
                try:
                    params["days"] = int(request.POST.get("days") or 0)
                except Exception:
                    params["days"] = 0
            elif action == "add_label":
                params["label"] = (request.POST.get("label") or "").strip()
            ColumnAutomation.objects.create(
                column=column, trigger=trigger, action=action,
                params=params, created_by=request.user,
            )

    return _render_modal(request, column)


@login_required
@require_http_methods(["POST"])
def column_automation_delete(request, automation_id):
    rule = get_object_or_404(ColumnAutomation, id=automation_id)
    column = rule.column
    if not can_edit_board(request.user, column.board):
        return HttpResponse("Sem permissão.", status=403)
    rule.delete()
    return _render_modal(request, column)
