# boards/views/activity.py
import re

from django.http import HttpResponse, JsonResponse
from django.shortcuts import render, get_object_or_404
from django.views.decorators.http import require_POST, require_http_methods
from django.contrib.auth.decorators import login_required
from django.template.loader import render_to_string
from django.db.models import Count, Q
from django.utils import timezone

from ..permissions import can_edit_board
from ..models import (
    Board,
    Card,
    CardAttachment,
    CardLog,
    CardSeen,
)
from .helpers import (
    _actor_html,
    _log_card,
    _save_base64_images_to_media,
    _ensure_attachments_and_activity_for_images,
    _extract_media_image_paths,
    process_mentions_and_notify,
)




@login_required
@require_http_methods(["GET"])
def activity_panel(request, card_id):
    card = get_object_or_404(Card, id=card_id, is_deleted=False)

    board = card.column.board
    memberships_qs = board.memberships.all()

    # regra de acesso (leitura): se tem memberships, precisa estar na lista
    if memberships_qs.exists():
        if not memberships_qs.filter(user=request.user).exists():
            return HttpResponse("Você não tem acesso a este quadro.", status=403)

    return render(request, "boards/partials/card_activity_panel.html", {"card": card})


@login_required
@require_POST
def add_activity(request, card_id):
    card = get_object_or_404(Card, id=card_id, is_deleted=False)
    board = card.column.board

    # ✅ ESCRITA: viewer não pode adicionar atividade
    if not can_edit_board(request.user, board):
        return HttpResponse("Somente leitura.", status=403)

    actor = _actor_html(request)

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
    board.version += 1
    board.save(update_fields=["version"])

    # menções: @handle e emails no texto bruto
    try:
        process_mentions_and_notify(
            request=request,
            board=board,
            card=card,
            source="activity",
            raw_text=raw,
        )
    except Exception:
        pass

    referenced_paths = _extract_media_image_paths(html or "", folder="quill")
    all_paths = list(dict.fromkeys((saved_paths or []) + (referenced_paths or [])))

    if all_paths:
        _ensure_attachments_and_activity_for_images(
            card=card,
            request=request,
            relative_paths=all_paths,
            actor=actor,
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

    try:
        card.refresh_from_db()
    except Exception:
        pass

    # 1) Atualiza painel de atividade (target do hx-post)
    activity_html = render_to_string(
        "boards/partials/card_activity_panel.html",
        {"card": card},
        request=request,
    )

    # 2) Atualiza anexos via OOB (funciona mesmo estando em outra aba)
    attachments = list(card.attachments.all())
    if attachments:
        attachments_items_html = "".join(
            render_to_string(
                "boards/partials/attachment_item.html",
                {"attachment": att},
                request=request,
            )
            for att in attachments
        )
    else:
        attachments_items_html = '<div class="cm-muted">Nenhum anexo ainda.</div>'

    oob_html = (
        '<div id="attachments-list" hx-swap-oob="innerHTML">'
        + attachments_items_html
        + "</div>"
    )

    return HttpResponse(activity_html + oob_html)


@require_POST
def quill_upload(request):
    return JsonResponse({"error": "Not implemented"}, status=501)



# boards/views/activity.py


@login_required
def cards_unread_activity(request, board_id):
    board = Board.objects.filter(id=board_id).first()
    if not board:
        return JsonResponse({"cards": {}})

    # segurança básica
    if not board.memberships.filter(user=request.user).exists():
        return JsonResponse({"cards": {}})

    # mapa: card_id -> last_seen_at
    seen_map = {
        cs.card_id: cs.last_seen_at
        for cs in CardSeen.objects.filter(
            user=request.user,
            card__column__board=board,
        )
    }

    # logs que NÃO são do próprio usuário
    logs = (
        CardLog.objects
        .filter(card__column__board=board)
        .exclude(content__icontains=request.user.email)
    )

    counts = {}

    for log in logs.select_related("card"):
        last_seen = seen_map.get(log.card_id)
        if last_seen and log.created_at <= last_seen:
            continue

        counts[log.card_id] = counts.get(log.card_id, 0) + 1

    return JsonResponse({"cards": counts})


# END boards/views/activity.py


