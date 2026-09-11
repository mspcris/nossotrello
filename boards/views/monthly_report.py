# boards/views/monthly_report.py
"""Aba "Mensal" do card (automação de entrega mensal) + API de monitoramento.

- monthly_panel      GET  -> partial da aba (recarrega após anexar)
- monthly_upload     POST -> anexa o relatório DIRETO na linha de um mês
- monthly_accept     POST -> "Aceitar mesmo assim" (anexo reprovado pela IA)
- monthly_reports_api GET -> JSON p/ projetos externos (TokenAuthentication do DRF)
"""
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.template.loader import render_to_string
from django.views.decorators.http import require_http_methods, require_POST

from ..models import Card, CardAttachment, ColumnAutomation, MonthlyReportEntry
from ..permissions import can_edit_board
from ..services import monthly_report as mr
from .attachments import _attached_label, _can_view_card
from .helpers import _actor_label, _log_card, sanitize_quill_html


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
def monthly_upload(request, card_id, entry_id):
    """Upload feito NA ABA MENSAL, já amarrado ao mês da linha.

    O arquivo vira um `CardAttachment` normal (aparece na aba Anexos e no
    histórico como qualquer outro) e, em vez de cair no ciclo pendente mais
    antigo, entra no mês que o gestor escolheu — é assim que ele quita os
    meses atrasados sem precisar renomear arquivo.

    Devolve JSON com o HTML já renderizado do painel e da lista de anexos: o
    input de arquivo mora dentro do #cm-main-form, então subir por htmx
    arrastaria junto todos os campos do card (inclusive o outro input `file`).
    """
    card = get_object_or_404(Card.objects.select_related("column__board"), id=card_id, is_deleted=False)
    board = card.column.board
    if not can_edit_board(request.user, board):
        return JsonResponse({"ok": False, "error": "Somente leitura."}, status=403)

    entry = get_object_or_404(MonthlyReportEntry, id=entry_id, card=card)

    if "file" not in request.FILES:
        return JsonResponse({"ok": False, "error": "Nenhum arquivo enviado."}, status=400)

    desc = sanitize_quill_html((request.POST.get("attachment_desc") or "").strip())
    attachment = CardAttachment.objects.create(
        card=card,
        file=request.FILES["file"],
        description=desc,
        created_by=request.user,
    )

    board.version += 1
    board.save(update_fields=["version"])

    _log_card(
        card,
        request,
        f"<p><strong>{_actor_label(request)}</strong> anexou {_attached_label(attachment.file)} "
        f"como o relatório de <strong>{mr.label(entry.month)}</strong>.</p>",
        attachment=attachment.file,
    )

    # miniatura (best-effort) — mesma cortesia do upload comum
    try:
        from boards.services.attach_thumbs import ensure_thumb_for_fieldfile
        ensure_thumb_for_fieldfile(attachment.file)
    except Exception:
        pass

    mr.attach_to_entry(card, entry, attachment, actor=request.user)

    card = Card.objects.get(id=card.id)
    items = list(card.attachments.all())
    attachments_html = "".join(
        render_to_string("boards/partials/attachment_item.html", {"attachment": att}, request=request)
        for att in items
    ) or '<div class="cm-muted">Nenhum anexo ainda.</div>'

    return JsonResponse({
        "ok": True,
        "panel_html": render_to_string(
            "boards/partials/monthly_report_panel.html",
            {
                "card": card,
                "monthly": mr.panel_context(card),
                "viewer_can_edit": True,
            },
            request=request,
        ),
        "attachments_html": attachments_html,
        "attachments_count": len(items),
    })


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
