# boards/views/attachments.py
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render, get_object_or_404
from django.views.decorators.http import require_POST
from django.utils.html import escape
from django.contrib.auth.decorators import login_required
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from urllib3 import request

from ..permissions import can_edit_board
from ..models import Card, CardAttachment, CardLog
from ..services.file_meta import display_name, file_meta
from .helpers import (
    _actor_label,
    _log_card,
    sanitize_quill_html,
)


_KIND_LABEL = {
    "image": "uma imagem",
    "video": "um vídeo",
    "pdf": "um PDF",
    "file": "um arquivo",
}


def _attached_label(fieldfile) -> str:
    """"anexou um vídeo" / "anexou uma imagem" / …

    O nome do arquivo já aparece no cartão do anexo logo abaixo, no próprio
    feed — repetir na linha de texto só polui.
    """
    kind = (file_meta(fieldfile) or {}).get("kind") or "file"
    return _KIND_LABEL.get(kind, _KIND_LABEL["file"])


def _flag(request, name: str) -> bool:
    return (request.POST.get(name) or "").strip().lower() in ("1", "true", "on", "yes")


def _can_view_card(user, card) -> bool:
    """Leitura do board do card — mesma regra do resto do app."""
    if not user or not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_superuser", False):
        return True

    board = card.column.board
    memberships = getattr(board, "memberships", None)
    if memberships is not None:
        return memberships.filter(user=user).exists()

    return bool(getattr(board, "created_by_id", None) == user.id)


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

    # `silent`: o anexo foi subido pelo compositor de Nova atividade e o usuário
    # tirou o chip antes de enviar. Nunca chegou a aparecer no feed — anunciar a
    # remoção de algo que ninguém viu só confunde.
    if _flag(request, "silent"):
        return HttpResponse("", status=200)

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

    # Vídeo: cópia normalizada em background, pra tocar no player de quem não
    # tem o codec do arquivo original (HEVC de iPhone, VP9, AVI antigo…).
    try:
        from boards.services.video_playable import ensure_playable_for_fieldfile
        ensure_playable_for_fieldfile(attachment.file)
    except Exception:
        pass

    # `defer_log`: veio do compositor de Nova atividade. O registro no feed sai
    # junto com o texto que o usuário ainda vai escrever — não aqui, senão a
    # mesma coisa apareceria em duas entradas.
    deferred = _flag(request, "defer_log")

    if not deferred:
        # O feed registra só QUE anexou e de que tipo. O nome do arquivo e a
        # descrição já aparecem no cartão do anexo logo abaixo (e na aba
        # Anexos) — repetir os dois deixava a entrada enorme para um vídeo.
        _log_card(
            card,
            request,
            f"<p><strong>{actor}</strong> anexou {_attached_label(attachment.file)}.</p>",
            attachment=attachment.file,
        )

    if deferred:
        meta = file_meta(attachment.file) or {}
        return JsonResponse({
            "ok": True,
            "id": attachment.id,
            "key": attachment.file.name,
            "name": meta.get("name") or "",
            "ext": meta.get("ext") or "",
            "kind": meta.get("kind") or "file",
            "icon_html": render_to_string(
                "boards/partials/file_icon.html",
                {"ext": meta.get("ext") or ""},
                request=request,
            ),
        })

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


@login_required
def video_playable_url(request, card_id, source_id):
    """`{ready, url}` da versão tocável de um vídeo deste card.

    O player chama aqui quando o `<video>` falha em decodificar o arquivo
    original — a conversão roda em background e pode ainda não ter terminado,
    então o front repete a consulta algumas vezes antes de desistir e oferecer
    o download.
    """
    card = get_object_or_404(
        Card.objects.select_related("column__board"),
        id=card_id,
        is_deleted=False,
    )
    if not _can_view_card(request.user, card):
        return HttpResponse("Sem acesso", status=403)

    key = str(source_id)

    # O vídeo tem que pertencer a ESTE card: como anexo vivo ou como arquivo de
    # alguma entrada do histórico. Sem isso, qualquer UUID viraria uma URL.
    belongs = (
        CardAttachment.all_objects.filter(card=card, file=key).exists()
        or CardLog.objects.filter(card=card, attachment=key).exists()
    )
    if not belongs:
        return HttpResponse("Sem acesso", status=403)

    from boards.services.video_playable import (
        playable_url_for_source_id,
        schedule_playable,
    )

    url = playable_url_for_source_id(source_id)
    if url:
        return JsonResponse({"ready": True, "url": url})

    schedule_playable(source_id)
    return JsonResponse({"ready": False, "url": ""})


# END boards/views/attachments.py
