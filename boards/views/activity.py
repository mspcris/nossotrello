# boards/views/activity.py
import re

from django.http import HttpResponse, JsonResponse
from django.shortcuts import render, get_object_or_404
from django.views.decorators.http import require_POST, require_http_methods
from django.contrib.auth.decorators import login_required
from django.template.loader import render_to_string
from django.db.models import Prefetch
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
    _save_base64_images_to_media,
    _ensure_attachments_and_activity_for_images,
    _extract_media_image_paths,
    process_mentions_and_notify,
)


def _safe_user_handle_or_email(u):
    """
    Preferir @handle quando existir; fallback para email.
    """
    try:
        h = getattr(getattr(u, "profile", None), "handle", None)
        h = (h or "").strip()
        if h:
            return f"@{h}"
    except Exception:
        pass

    try:
        e = (getattr(u, "email", "") or "").strip()
        if e:
            return e
    except Exception:
        pass

    return ""


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

    parents = (
        card.logs
        .filter(reply_to__isnull=True)
        .select_related("actor")
        .prefetch_related(
            Prefetch(
                "replies",
                queryset=CardLog.objects.select_related("actor").order_by("created_at"),
            )
        )
        .order_by("-created_at")
    )

    return render(
        request,
        "boards/partials/card_activity_panel.html",
        {"card": card, "logs": parents},
    )









@login_required
@require_POST
def add_activity(request, card_id):
    card = get_object_or_404(Card, id=card_id, is_deleted=False)
    board = card.column.board

    # ✅ ESCRITA: viewer não pode adicionar atividade
    if not can_edit_board(request.user, board):
        return HttpResponse("Somente leitura.", status=403)

    raw = (request.POST.get("content") or "").strip()
    if not raw:
        return HttpResponse("Conteúdo vazio", status=400)

    reply_to_id = (request.POST.get("reply_to") or "").strip()
    parent_log = None
    if reply_to_id:
        try:
            parent_log = card.logs.select_related("actor").filter(id=reply_to_id).first()
        except Exception:
            parent_log = None

    html, saved_paths = _save_base64_images_to_media(raw, folder="quill")

    def _trim_quill_empty_blocks(s: str) -> str:
        s = (s or "").strip()

        # remove blocos vazios no começo/fim (padrão Quill)
        # <p><br></p>, <p><br/></p>, <p>&nbsp;</p>, etc.
        s = re.sub(
            r'^(?:\s*<p>(?:\s|&nbsp;|<br\s*/?>)*</p>\s*)+',
            "",
            s,
            flags=re.I,
        )
        s = re.sub(
            r'(?:\s*<p>(?:\s|&nbsp;|<br\s*/?>)*</p>\s*)+$',
            "",
            s,
            flags=re.I,
        )

        return s.strip()

    clean_html = _trim_quill_empty_blocks(html)
    if not clean_html:
        return HttpResponse("Conteúdo vazio", status=400)

    # ✅ Agora: atividade “normal” vira CardLog puro (sem wrapper).
    # ✅ Resposta (reply) também vira CardLog puro com reply_to.
    CardLog.objects.create(
        card=card,
        actor=request.user,
        reply_to=parent_log if parent_log else None,
        content=clean_html,
        attachment=None,
    )

    board.version += 1
    board.save(update_fields=["version"])

    # menções: @handle e emails no texto bruto
    # ✅ Se for reply: notifica o autor original via mentions (sem poluir o HTML salvo)
    try:
        raw_for_mentions = raw
        if parent_log and parent_log.actor:
            who = _safe_user_handle_or_email(parent_log.actor)
            if who:
                raw_for_mentions = f"{who} {raw}"

        process_mentions_and_notify(
            request=request,
            board=board,
            card=card,
            source="activity",
            raw_text=raw_for_mentions,
        )
    except Exception:
        pass

    referenced_paths = _extract_media_image_paths(clean_html or "", folder="quill")
    all_paths = list(dict.fromkeys((saved_paths or []) + (referenced_paths or [])))

    if all_paths:
        _ensure_attachments_and_activity_for_images(
            card=card,
            request=request,
            relative_paths=all_paths,
            actor=_actor_html(request),
            context_label="atividade",
        )

    # garante anexos também para imagens já existentes em /media/quill/
    img_urls = re.findall(r'src=(["\'])([^"\']+)\1', clean_html, flags=re.IGNORECASE)
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
    parents = (
        card.logs
        .filter(reply_to__isnull=True)
        .select_related("actor")
        .prefetch_related(
            Prefetch(
                "replies",
                queryset=CardLog.objects.select_related("actor").order_by("created_at"),
            )
        )
        .order_by("-created_at")
    )

    activity_html = render_to_string(
        "boards/partials/card_activity_panel.html",
        {"card": card, "logs": parents},
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
