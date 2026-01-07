# boards/views/attachments.py
from django.http import HttpResponse
from django.shortcuts import render, get_object_or_404
from django.views.decorators.http import require_POST
from django.utils.html import escape
from django.contrib.auth.decorators import login_required
from django.template.loader import render_to_string

from ..permissions import can_edit_board
from ..models import Card, CardAttachment
from .helpers import (
    _actor_label,
    _log_card,
)


@login_required
@require_POST
def delete_attachment(request, card_id, attachment_id):
    card = get_object_or_404(Card, id=card_id, is_deleted=False)
    attachment = get_object_or_404(CardAttachment, id=attachment_id, card=card)

    board = card.column.board
    # ✅ ESCRITA
    if not can_edit_board(request.user, board):
        return HttpResponse("Somente leitura.", status=403)

    actor = _actor_label(request)

    file_name = (attachment.file.name or "")
    pretty_name = file_name.split("/")[-1] if file_name else "arquivo"
    desc = (attachment.description or "").strip()

    should_delete_file = file_name.startswith("attachments/")

    if should_delete_file:
        try:
            if CardAttachment.objects.filter(file=file_name).exclude(id=attachment.id).exists():
                should_delete_file = False
        except Exception:
            pass

    if should_delete_file:
        try:
            attachment.file.delete(save=False)
        except Exception:
            pass

    attachment.delete()

    board.version += 1
    board.save(update_fields=["version"])

    if desc:
        _log_card(
            card,
            request,
            f"<p><strong>{actor}</strong> removeu o anexo <strong>{escape(pretty_name)}</strong> — {escape(desc)}.</p>",
        )
    else:
        _log_card(
            card,
            request,
            f"<p><strong>{actor}</strong> removeu o anexo <strong>{escape(pretty_name)}</strong>.</p>",
        )

    return HttpResponse("", status=200)


@login_required
@require_POST
def add_attachment(request, card_id):
    card = get_object_or_404(Card, id=card_id, is_deleted=False)
    board = card.column.board

    if not can_edit_board(request.user, board):
        return HttpResponse("Somente leitura.", status=403)

    actor = _actor_label(request)

    if "file" not in request.FILES:
        return HttpResponse("Nenhum arquivo enviado", status=400)

    uploaded = request.FILES["file"]
    desc = (request.POST.get("description") or "").strip()

    attachment = CardAttachment.objects.create(
        card=card,
        file=uploaded,
        description=desc,
    )

    board.version += 1
    board.save(update_fields=["version"])

    pretty_name = attachment.file.name.split("/")[-1]
    if desc:
        _log_card(
            card,
            request,
            f"<p><strong>{actor}</strong> adicionou um anexo: <strong>{escape(pretty_name)}</strong> — {escape(desc)}.</p>",
            attachment=attachment.file,
        )
    else:
        _log_card(
            card,
            request,
            f"<p><strong>{actor}</strong> adicionou um anexo: <strong>{escape(pretty_name)}</strong>.</p>",
            attachment=attachment.file,
        )

    # Recarrega para garantir estado real (ordem/relacionamentos)
    card = Card.objects.get(id=card.id)

    # 1) HTML do item recém inserido (mantém UX de append imediato)
    attachment_html = render_to_string(
        "boards/partials/attachment_item.html",
        {"attachment": attachment},
        request=request,
    )

    # 2) OOB: reconcilia a lista inteira (ganha de corridas de swap/poll)
    items = list(card.attachments.all())
    if items:
        full_list_inner = "".join(
            render_to_string(
                "boards/partials/attachment_item.html",
                {"attachment": att},
                request=request,
            )
            for att in items
        )
    else:
        full_list_inner = '<div class="cm-muted">Nenhum anexo ainda.</div>'

    oob_refresh = (
        f'<div id="attachments-list" hx-swap-oob="innerHTML">{full_list_inner}</div>'
    )

    return HttpResponse(attachment_html + oob_refresh, content_type="text/html")

# END boards/views/attachments.py
