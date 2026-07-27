# boards/views/attachments.py
from django.http import HttpResponse
from django.shortcuts import render, get_object_or_404
from django.views.decorators.http import require_POST
from django.utils.html import escape
from django.contrib.auth.decorators import login_required
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from urllib3 import request

from ..permissions import can_edit_board
from ..models import Card, CardAttachment, CardLog
from ..services.file_meta import display_name
from .helpers import (
    _actor_label,
    _log_card,
    sanitize_quill_html,
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
    pretty_name = display_name(attachment.file) if file_name else "arquivo"
    desc = strip_tags((attachment.description or "")).strip()

    # Soft-delete: some do card, mas a linha e os bytes ficam. O StoredFile é
    # deduplicado por checksum — outro card pode apontar pro mesmo blob — e o
    # histórico do card precisa continuar auditável.
    attachment.soft_delete()

    # Marca os logs do card que citam esse arquivo como removidos, a menos que
    # outro anexo VIVO do mesmo card ainda aponte pro mesmo arquivo.
    if file_name:
        try:
            still_used = (
                CardAttachment.objects
                .filter(card=card, file=file_name)
                .exclude(id=attachment.id)
                .exists()
            )
            if not still_used:
                CardLog.objects.filter(
                    card=card,
                    attachment=file_name,
                ).update(attachment_deleted=True)
        except Exception:
            pass

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
    # ✅ evita conflito com o name="description" do card (aba Descrição).
    # O form posta o campo como `attachment_desc`; mantemos os fallbacks legados.
    raw_desc = (
        request.POST.get("attachment_desc")
        or request.POST.get("attachment_description")
        or request.POST.get("description")
        or ""
    ).strip()
    # A descrição pode conter HTML (Quill / colagem). Sanitiza no MESMO allowlist
    # da descrição do card, pra renderizar formatada com |safe sem risco de XSS.
    desc = sanitize_quill_html(raw_desc)

    attachment = CardAttachment.objects.create(
        card=card,
        file=uploaded,
        description=desc,
        created_by=request.user,
    )

    board.version += 1
    board.save(update_fields=["version"])

    # miniatura de PDF/vídeo (best-effort) — gera já no upload p/ o 1º render do feed
    try:
        from boards.services.attach_thumbs import ensure_thumb_for_fieldfile
        ensure_thumb_for_fieldfile(attachment.file)
    except Exception:
        pass

    # NÃO usar attachment.file.name: no DatabaseStorage ele é a chave UUID do
    # StoredFile. Resolve o nome real — o mesmo que aparece na lista de anexos
    # e no Content-Disposition do download, pra não divergir do que o usuário vê.
    pretty_name = display_name(attachment.file) or (uploaded.name or "").split("/")[-1]
    if desc:
        # desc já vem sanitizado -> entra como HTML (bloco próprio, fora do <p>,
        # pra não quebrar o layout quando tiver títulos/listas).
        _log_card(
            card,
            request,
            f"<p><strong>{actor}</strong> adicionou um anexo: <strong>{escape(pretty_name)}</strong>:</p>"
            f"<div class=\"cm-attach-desc\">{desc}</div>",
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

    return HttpResponse(oob_refresh, content_type="text/html")


# END boards/views/attachments.py
