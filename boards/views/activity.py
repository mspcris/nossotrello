# boards/views/activity.py
import re
import json

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


def _compact_quill_html(s: str) -> str:
    s = (s or "").strip()

    # normaliza NBSP
    s = s.replace("\u00A0", " ")
    s = re.sub(r"&nbsp;", " ", s, flags=re.I)

    # remove spans vazios comuns do Quill (cursor/ui/etc)
    s = re.sub(r"<span[^>]*>\s*</span>", "", s, flags=re.I)

    # remove <p> vazios mesmo se tiverem spans vazios e <br ...>
    empty_p_re = re.compile(
        r"<p[^>]*>(?:\s|<br[^>]*>|&nbsp;|<span[^>]*>\s*</span>)*</p>",
        flags=re.I,
    )

    # aplica em loop para “varrer” sequências grandes
    while True:
        new_s = empty_p_re.sub("", s)
        if new_s == s:
            break
        s = new_s

    # remove div vazio (cinturão e suspensório)
    s = re.sub(
        r"<div[^>]*>(?:\s|<br[^>]*>|&nbsp;|<span[^>]*>\s*</span>)*</div>",
        "",
        s,
        flags=re.I,
    )

    # colapsa múltiplos <br>
    s = re.sub(r"(?:<br[^>]*>\s*){2,}", "<br>", s, flags=re.I)

    return s.strip()


def _parse_delta(delta_raw: str):
    """
    Aceita string JSON do Delta. Retorna dict ou {}.
    """
    try:
        if not delta_raw:
            return {}
        obj = json.loads(delta_raw)
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


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

    # legado: HTML
    raw_html = (request.POST.get("content") or "").strip()

    # ✅ novo: Delta + texto (source of truth)
    delta_raw = (request.POST.get("delta") or "").strip()
    text_raw = (request.POST.get("text") or "").strip()

    # regra mínima: precisa ter delta OU html
    if not delta_raw and not raw_html:
        return HttpResponse("Conteúdo vazio", status=400)

    reply_to_id = (request.POST.get("reply_to") or "").strip()
    parent_log = None
    if reply_to_id:
        try:
            parent_log = card.logs.select_related("actor").filter(id=reply_to_id).first()
        except Exception:
            parent_log = None

    # se veio html, mantém pipeline atual (base64->media etc)
    saved_paths = []
    clean_html = ""
    if raw_html:
        html, saved_paths = _save_base64_images_to_media(raw_html, folder="quill")
        clean_html = _compact_quill_html(html)

    # parse delta
    delta_obj = _parse_delta(delta_raw)

    # validação: se não tem texto e não tem html útil e delta vazio => vazio
    if not text_raw and not clean_html and not delta_obj:
        return HttpResponse("Conteúdo vazio", status=400)

    log = CardLog.objects.create(
        card=card,
        actor=request.user,
        reply_to=parent_log if parent_log else None,
        content=clean_html,          # legado (pode ficar vazio quando delta é o foco)
        content_delta=delta_obj,     # ✅ novo
        content_text=text_raw,       # ✅ novo
        attachment=None,
    )

    board.version += 1
    board.save(update_fields=["version"])

    # menções: usa TEXTO (mais estável); fallback para HTML se necessário
    try:
        raw_for_mentions = text_raw or raw_html
        if parent_log and parent_log.actor:
            who = _safe_user_handle_or_email(parent_log.actor)
            if who:
                raw_for_mentions = f"{who} {raw_for_mentions}"

        process_mentions_and_notify(
            request=request,
            board=board,
            card=card,
            source="activity",
            raw_text=raw_for_mentions,
        )
    except Exception:
        pass

    # attachments via imagens (se existirem no HTML legado)
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
    if clean_html:
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

    # logs que NÃO são do próprio usuário (mais correto que procurar email no conteúdo)
    logs = (
        CardLog.objects
        .filter(card__column__board=board)
        .exclude(actor=request.user)
    )

    counts = {}

    for log in logs.select_related("card"):
        last_seen = seen_map.get(log.card_id)
        if last_seen and log.created_at <= last_seen:
            continue

        counts[log.card_id] = counts.get(log.card_id, 0) + 1

    return JsonResponse({"cards": counts})
