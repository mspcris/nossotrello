# boards/views/column_automation.py
"""Automação da coluna: modal (listar + adicionar) e remover regra."""
import re

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
    from boards.services import monthly_report as mr
    from boards.services import hesk_gestores
    rules = list(column.automations.all())
    for r in rules:
        if r.action == "monthly_report":
            r.monthly = mr.rule_params(r)
            r.monthly["extra_ids_csv"] = ",".join(str(i) for i in r.monthly["extra_user_ids"])
    return render(request, "boards/partials/column_automation_modal.html", {
        "column": column,
        "rules": [r for r in rules if r.is_active],
        "hesk_gestores": hesk_gestores.gestores_do_posto(column.board.name),
        "hesk_available": hesk_gestores.available(),
        "posto_nome": column.board.name,
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
            # dias parado (gatilho stale) — nome próprio p/ não colidir com 'days' da ação
            if trigger == "stale":
                try:
                    params["days"] = int(request.POST.get("stale_days") or 0)
                except Exception:
                    params["days"] = 0
            if action == "send_email":
                params["email"] = (request.POST.get("email") or "").strip()
                msg = (request.POST.get("message") or "").strip()
                if msg:
                    params["message"] = msg[:2000]
            elif action == "send_whatsapp":
                params["phone"] = (request.POST.get("phone") or "").strip()
                msg = (request.POST.get("message") or "").strip()
                if msg:
                    params["message"] = msg[:2000]
            elif action == "notify_placer":
                # destinatário é derivado (quem colocou o card); só mensagem opcional
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
                color = (request.POST.get("label_color") or "").strip()
                params["label_color"] = color if re.match(r"^#[0-9a-fA-F]{6}$", color) else "#888888"
            elif action == "monthly_report":
                # recorrência: só com o gatilho "anexo adicionado" e uma por coluna
                trigger = "attach"
                try:
                    params["day"] = max(1, min(int(request.POST.get("day") or 15), 28))
                except Exception:
                    params["day"] = 15
                params["recipient_email"] = (request.POST.get("recipient_email") or "").strip().lower()
                params["extra_user_ids"] = [
                    int(x) for x in request.POST.getlist("extra_user_ids") if str(x).isdigit()
                ]
                params["ai_validate"] = bool(request.POST.get("ai_validate"))
                params["ai_instructions"] = (request.POST.get("ai_instructions") or "").strip()[:2000]
                sm = (request.POST.get("start_month") or "").strip()
                if re.match(r"^\d{4}-\d{2}$", sm):
                    params["start_month"] = sm
            # edição: se veio rule_id desta coluna, atualiza em vez de criar
            rule_id = request.POST.get("rule_id")
            rule = None
            if rule_id:
                rule = ColumnAutomation.objects.filter(id=rule_id, column=column).first()
            if action == "monthly_report" and rule is None:
                rule = ColumnAutomation.objects.filter(column=column, action="monthly_report").first()
                if rule is not None:
                    params.setdefault("start_month", (rule.params or {}).get("start_month", ""))
            if rule:
                rule.trigger = trigger
                rule.action = action
                rule.params = params
                if action == "monthly_report" and not rule.is_active:
                    rule.is_active = True
                    rule.save(update_fields=["trigger", "action", "params", "is_active"])
                else:
                    rule.save(update_fields=["trigger", "action", "params"])
            else:
                rule = ColumnAutomation.objects.create(
                    column=column, trigger=trigger, action=action,
                    params=params, created_by=request.user,
                )
            if action == "monthly_report":
                from boards.services import monthly_report as mr
                mr.invalidate_cache()
                # ativação: monta o livro-razão dos cards já existentes na coluna
                try:
                    from ..models import Card
                    earliest = None
                    for c in Card.objects.filter(column=column, is_archived=False, counter_mode=""):
                        mr.seed_card(rule, c, actor=request.user)
                        first = rule.monthly_entries.filter(card=c).order_by("month").values_list("month", flat=True).first()
                        if first and (earliest is None or first < earliest):
                            earliest = first
                    if earliest and not (rule.params or {}).get("start_month"):
                        p2 = dict(rule.params or {})
                        p2["start_month"] = earliest.strftime("%Y-%m")
                        rule.params = p2
                        rule.save(update_fields=["params"])
                except Exception:
                    pass

    return _render_modal(request, column)


@login_required
@require_http_methods(["POST"])
def column_automation_delete(request, automation_id):
    rule = get_object_or_404(ColumnAutomation, id=automation_id)
    column = rule.column
    if not can_edit_board(request.user, column.board):
        return HttpResponse("Sem permissão.", status=403)
    if rule.action == "monthly_report":
        # recorrência: desliga (o histórico do livro-razão fica); não apaga
        rule.is_active = False
        rule.save(update_fields=["is_active"])
        from boards.services.monthly_report import invalidate_cache
        invalidate_cache()
    else:
        rule.delete()
    return _render_modal(request, column)
