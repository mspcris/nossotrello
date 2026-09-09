# boards/views/monthly_report.py
"""Aba "Mensal" do card (automação de entrega mensal) + API de monitoramento.

- monthly_panel      GET  -> partial da aba (recarrega após anexar)
- monthly_accept     POST -> "Aceitar mesmo assim" (anexo reprovado pela IA)
- monthly_reports_api GET -> JSON p/ projetos externos (TokenAuthentication do DRF)
"""
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_http_methods, require_POST

from ..models import Card, ColumnAutomation, MonthlyReportEntry
from ..permissions import can_edit_board
from ..services import monthly_report as mr
from .attachments import _can_view_card


def _render_panel(request, card):
    return render(request, "boards/partials/monthly_report_panel.html", {
        "card": card,
        "monthly": mr.panel_context(card),
        "viewer_can_edit": can_edit_board(request.user, card.column.board),
    })


@login_required
@require_http_methods(["GET"])
def monthly_panel(request, card_id):
    card = get_object_or_404(Card.objects.select_related("column__board"), id=card_id, is_deleted=False)
    if not _can_view_card(request.user, card):
        return HttpResponse("Sem acesso", status=403)
    return _render_panel(request, card)


@login_required
@require_POST
def monthly_accept(request, card_id, entry_id):
    card = get_object_or_404(Card.objects.select_related("column__board"), id=card_id, is_deleted=False)
    if not can_edit_board(request.user, card.column.board):
        return HttpResponse("Somente leitura.", status=403)
    entry = get_object_or_404(MonthlyReportEntry, id=entry_id, card=card)
    mr.accept(entry, request.user)
    return _render_panel(request, card)


def _entry_json(e, card):
    board = card.column.board
    return {
        "board_id": board.id,
        "posto": board.name,
        "card_id": card.id,
        "card_title": card.title,
        "month": e.month.strftime("%Y-%m"),
        "due_on": e.due_on.isoformat(),
        "status": e.status,
        "attached_at": e.attached_at.isoformat() if e.attached_at else None,
        "attached_by": (e.attached_by.email if e.attached_by else None),
        "attachment_id": e.attachment_id,
        "ai_verdict": e.ai_verdict,
        "ai_summary": e.ai_summary,
        "reminded_at": e.reminded_at.isoformat() if e.reminded_at else None,
        "notified_at": e.notified_at.isoformat() if e.notified_at else None,
        "card_url": mr._card_link(card),
    }


def monthly_reports_api(request):
    """GET /api/monthly-reports/?board=34[&all=1]

    Autenticação: `Authorization: Token <token>` (DRF TokenAuthentication, o
    mesmo token que o Hesk já usa) ou sessão de staff. Sem `all=1` devolve só
    o ciclo em aberto de cada card (ou o mês corrente, quando entregue).
    """
    from rest_framework.authentication import TokenAuthentication
    from rest_framework.exceptions import AuthenticationFailed

    user = request.user if request.user.is_authenticated else None
    if user is None:
        try:
            auth = TokenAuthentication().authenticate(request)
        except AuthenticationFailed:
            auth = None
        if auth:
            user = auth[0]
    if user is None or not user.is_active:
        return JsonResponse({"ok": False, "error": "unauthorized"}, status=401)

    qs = MonthlyReportEntry.objects.select_related(
        "card__column__board", "attached_by",
    ).filter(rule__is_active=True, card__is_archived=False)
    board = (request.GET.get("board") or "").strip()
    if board.isdigit():
        qs = qs.filter(card__column__board_id=int(board))

    if request.GET.get("all"):
        rows = [_entry_json(e, e.card) for e in qs.order_by("card__column__board__name", "card__title", "month")]
    else:
        today = mr.today_local()
        cur = mr.month_first(today)
        by_card = {}
        for e in qs.order_by("card_id", "month"):
            slot = by_card.setdefault(e.card_id, {"open": None, "current": None, "card": e.card})
            if e.status in ("pending", "rejected", "validating") and slot["open"] is None and e.month <= cur:
                slot["open"] = e
            if e.month == cur:
                slot["current"] = e
        rows = []
        for slot in by_card.values():
            e = slot["open"] or slot["current"]
            if e is not None:
                rows.append(_entry_json(e, slot["card"]))
        rows.sort(key=lambda r: (r["posto"], r["card_title"]))

    return JsonResponse({"ok": True, "today": mr.today_local().isoformat(), "count": len(rows), "rows": rows})
