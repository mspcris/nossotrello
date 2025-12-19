# boards/views/activity.py

import re

from django.http import HttpResponse
from django.shortcuts import render, get_object_or_404
from django.views.decorators.http import require_POST, require_http_methods
from django.contrib.auth.decorators import login_required
from django.core.files.storage import default_storage

from .helpers import (
    _actor_label,
    _log_card,
    _save_base64_images_to_media,
    _ensure_attachments_and_activity_for_images,
    _extract_media_image_paths,
    _ensure_attachments_and_activity_for_images,
    _actor_label,
    Card,
    CardAttachment,
)


@login_required
@require_http_methods(["GET"])
def activity_panel(request, card_id):
    card = get_object_or_404(Card, id=card_id, is_deleted=False)

    board = card.column.board
    memberships_qs = board.memberships.all()

    if memberships_qs.exists():
        if not memberships_qs.filter(user=request.user).exists():
            return HttpResponse("Você não tem acesso a este quadro.", status=403)

    return render(request, "boards/partials/card_activity_panel.html", {"card": card})


@require_POST
def add_activity(request, card_id):
    card = get_object_or_404(Card, id=card_id)
    actor = _actor_label(request)

    raw = (request.POST.get("content") or "").strip()
    if not raw:
        return HttpResponse("Conteúdo vazio", status=400)

    html, saved_paths = _save_base64_images_to_media(raw, folder="quill")

    _log_card(
        card,
        request,
        f"<p><strong>{actor}</strong> adicionou uma atividade:</p>{html}",
        attachment=None,
    )

    # BUGFIX: antes chamava ensure_attachments_and_activity_for_images (não existe)
    referenced_paths = _extract_media_image_paths(html or "", folder="quill")
    all_paths = list(dict.fromkeys((saved_paths or []) + (referenced_paths or [])))

    if all_paths:
        _ensure_attachments_and_activity_for_images(
        card=card,
        request=request,
        relative_paths=all_paths,
        actor=_actor_label(request),
        context_label="atividade",
    )

    # garante anexos também para imagens já existentes em /media/quill/
    img_urls = re.findall(r'src=(["\'])([^"\']+)\1', html, flags=re.IGNORECASE)
    for _q, url in img_urls:
        if "/media/quill/" not in (url or ""):
            continue

        relative_path = url.split("/media/")[-1].strip()
        if not relative_path:
            continue

        try:
            if not card.attachments.filter(file=relative_path).exists():
                CardAttachment.objects.create(card=card, file=relative_path)
        except Exception:
            pass

    rendered = render(
        request,
        "boards/partials/card_activity_panel.html",
        {"card": card},
    ).content.decode("utf-8")

    return HttpResponse(rendered)


@require_POST
def quill_upload(request):
    # Mantendo 501 por enquanto (mesmo comportamento do seu stub).
    # Quando quiser implementar de verdade, a gente centraliza upload aqui.
    from django.http import JsonResponse
    return JsonResponse({"error": "Not implemented"}, status=501)
