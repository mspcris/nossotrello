# boards/views/activity.py
import re
import json
import os
import uuid

from django.http import HttpResponse, JsonResponse
from django.shortcuts import render, get_object_or_404
from django.views.decorators.http import require_POST, require_http_methods
from django.contrib.auth.decorators import login_required
from django.template.loader import render_to_string
from django.db.models import Prefetch
from django.utils.html import escape

from django.core.files.storage import default_storage

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

from boards.services.notifications import (
    build_card_snapshot,
    format_card_message,
    notify_users_for_card,
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
    Aceita JSON do Delta do Quill.
    Retorna dict no formato {"ops":[...]} ou {}.
    """
    try:
        if not delta_raw:
            return {}

        obj = json.loads(delta_raw)

        # Quill normalmente é {"ops":[...]} (dict)
        if isinstance(obj, dict):
            return obj

        # Alguns front-ends mandam só a lista de ops
        if isinstance(obj, list):
            return {"ops": obj}

        return {}
    except Exception:
        return {}


def _extract_plain_text_from_delta(delta_obj: dict) -> str:
    """
    Extrai texto "humano" do Delta (ignora imagens/embeds).
    """
    try:
        ops = (delta_obj or {}).get("ops", [])
        if not isinstance(ops, list):
            return ""

        parts = []
        for op in ops:
            if not isinstance(op, dict):
                continue
            ins = op.get("insert")
            if isinstance(ins, str):
                parts.append(ins)
        # normaliza whitespace
        txt = "".join(parts)
        txt = txt.replace("\u00A0", " ")
        txt = re.sub(r"[ \t]+\n", "\n", txt)
        return txt.strip()
    except Exception:
        return ""


def _extract_media_image_paths_from_delta(delta_obj: dict, folder: str = "quill") -> list[str]:
    """
    Extrai paths relativos (ex: 'quill/abc.png') de imagens inseridas no Delta:
      ops: [{ insert: { image: "/media/quill/abc.png" } }, ...]
    Retorna lista de paths relativos sem barra inicial.
    """
    paths: list[str] = []
    try:
        ops = (delta_obj or {}).get("ops", [])
        if not isinstance(ops, list):
            return []

        for op in ops:
            if not isinstance(op, dict):
                continue
            ins = op.get("insert")
            if not isinstance(ins, dict):
                continue

            url = ins.get("image")
            if not isinstance(url, str) or not url:
                continue

            # aceita /media/quill/... ou URL absoluta contendo /media/quill/...
            if "/media/" not in url:
                continue
            if f"/media/{folder}/" not in url:
                continue

            rel = url.split("/media/")[-1].lstrip("/")
            if rel:
                paths.append(rel)

    except Exception:
        return []

    # unique preservando ordem
    return list(dict.fromkeys(paths))


def _build_comment_log_html_for_images(actor_handle_or_email: str, relative_paths: list[str]) -> str:
    """
    HTML simples para aparecer no FEED (thumb pequena + link).
    """
    if not relative_paths:
        return ""

    rp = relative_paths[0].lstrip("/")
    url = f"/media/{rp}"
    filename = os.path.basename(rp)

    who = actor_handle_or_email.strip() if actor_handle_or_email else ""
    prefix = f"{escape(who)} adicionou uma imagem na atividade:" if who else "Adicionou uma imagem na atividade:"

    return f"""
    <div class="cm-activity-img-comment">
      <div class="cm-muted">{prefix}</div>
      <div class="cm-attach">
        <a class="cm-attach-file" href="{escape(url)}" target="_blank" rel="noopener">{escape(filename)}</a>
        <a href="{escape(url)}" target="_blank" rel="noopener" class="cm-attach-thumb" data-preview-src="{escape(url)}">
          <img src="{escape(url)}" alt="">
          <span class="cm-attach-zoom" aria-hidden="true">🔍</span>
        </a>
      </div>
    </div>
    """.strip()


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

    parents_qs = (
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

    parents = _decorate_logs_for_feed(parents_qs)

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

    if not can_edit_board(request.user, board):
        return HttpResponse("Somente leitura.", status=403)

    # legado: HTML
    raw_html = (request.POST.get("content") or "").strip()

    # novo: Delta + texto (source of truth)
    delta_raw = (request.POST.get("delta") or "").strip()
    text_raw = (request.POST.get("text") or "").strip()

    # regra mínima: precisa ter delta OU html OU texto
    if not delta_raw and not raw_html and not text_raw:
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
    delta_text = _extract_plain_text_from_delta(delta_obj)
    effective_text = (text_raw or "").strip() or (delta_text or "").strip()


    # validação final: se não tem texto, não tem html útil e delta vazio => vazio
    if not text_raw and not clean_html and not delta_obj:
        return HttpResponse("Conteúdo vazio", status=400)

    # menções: usa TEXTO (mais estável); fallback para HTML se necessário
    try:
        raw_for_mentions = raw_html or text_raw
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

    # ============================================================
    # Descobrir imagens vindas do HTML e do DELTA
    # ============================================================
    referenced_paths_html = _extract_media_image_paths(clean_html or "", folder="quill")
    referenced_paths_delta = _extract_media_image_paths_from_delta(delta_obj or {}, folder="quill")

    all_paths = list(
        dict.fromkeys(
            (saved_paths or [])
            + (referenced_paths_html or [])
            + (referenced_paths_delta or [])
        )
    )

    # ============================================================
    # Se NÃO tem imagem: cria o log normal (delta + texto + html)
    # ============================================================
    if not all_paths:
        CardLog.objects.create(
            card=card,
            actor=request.user,
            reply_to=parent_log if parent_log else None,
            content=clean_html,
            content_delta=delta_obj,
            content_text=effective_text,
            attachment=None,
        )

        # Notifica (best-effort)
        try:
            followers = [cf.user for cf in card.follows.select_related("user").all()]
            followers = [u for u in followers if u and u.id != request.user.id]
            if followers:
                snap = build_card_snapshot(card=card)
                msg = format_card_message(title_prefix="📝 Atividade no card", snap=snap)
                notify_users_for_card(
                    card=card,
                    recipients=followers,
                    subject=f"Atividade no card: {snap.title}",
                    message=msg,
                    include_link_as_second_whatsapp_message=True,
                )
        except Exception:
            pass

        board.version += 1
        board.save(update_fields=["version"])

    # ============================================================
    # Se TEM imagem:
    # - garante anexos
    # - COMMENTS somente se houver texto (texto+imagem)
    # - FILES somente se for imagem-only
    # ============================================================
    if all_paths:
        # garante anexos
        for rp in all_paths:
            rel = (rp or "").lstrip("/")
            if not rel:
                continue
            try:
                if not card.attachments.filter(file=rel).exists():
                    CardAttachment.objects.create(card=card, file=rel)
            except Exception:
                pass

        who = _safe_user_handle_or_email(request.user)

        # --------------------------
        # COMMENTS: só se tiver texto
        # --------------------------
        if effective_text:
            try:
                thumb_html = _build_comment_log_html_for_images(who, all_paths)

                html_no_img = (clean_html or "")
                if html_no_img:
                    html_no_img = re.sub(r"<img[^>]*>", "", html_no_img, flags=re.I)
                    html_no_img = _compact_quill_html(html_no_img)

                if not html_no_img:
                    html_no_img = f"<p>{escape(effective_text)}</p>"

                comments_html = (html_no_img or "") + (thumb_html or "")

                CardLog.objects.create(
                    card=card,
                    actor=request.user,
                    reply_to=parent_log if parent_log else None,
                    content=comments_html,
                    content_delta={},             # FORÇA HTML => sem imagem grande
                    content_text=effective_text,  # mantém texto real
                    attachment=None,
                )

                # Notifica seguidores do card (exceto o autor da ação)
                try:
                    followers = [cf.user for cf in card.follows.select_related("user").all()]
                    followers = [u for u in followers if u and u.id != request.user.id]

                    if followers:
                        snap = build_card_snapshot(card=card)
                        msg = format_card_message(
                            title_prefix="📝 Atividade no card",
                            snap=snap,
                        )
                        notify_users_for_card(
                            card=card,
                            recipients=followers,
                            subject=f"Atividade no card: {snap.title}",
                            message=msg,
                            include_link_as_second_whatsapp_message=True,
                        )
                except Exception:
                    pass

                board.version += 1
                board.save(update_fields=["version"])
            except Exception:
                pass

        # --------------------------
        # FILES: somente se for imagem-only
        # --------------------------
        else:
            try:
                files_html = _build_comment_log_html_for_images(who, all_paths)
                if files_html:
                    CardLog.objects.create(
                        card=card,
                        actor=request.user,
                        reply_to=parent_log if parent_log else None,
                        content=files_html,
                        content_delta={},
                        content_text="",  # vazio => cai em files
                        attachment=None,
                    )

                # Notifica seguidores do card (exceto o autor da ação)
                try:
                    followers = [cf.user for cf in card.follows.select_related("user").all()]
                    followers = [u for u in followers if u and u.id != request.user.id]

                    if followers:
                        snap = build_card_snapshot(card=card)
                        msg = format_card_message(
                            title_prefix="📝 Atividade no card",
                            snap=snap,
                        )
                        notify_users_for_card(
                            card=card,
                            recipients=followers,
                            subject=f"Atividade no card: {snap.title}",
                            message=msg,
                            include_link_as_second_whatsapp_message=True,
                        )
                except Exception:
                    pass

                board.version += 1
                board.save(update_fields=["version"])
            except Exception:
                pass


    # ============================================================
    # Atualiza UI
    # ============================================================
    try:
        card.refresh_from_db()
    except Exception:
        pass

    parents_qs = (
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

    parents = _decorate_logs_for_feed(parents_qs)

    activity_html = render_to_string(
        "boards/partials/card_activity_panel.html",
        {"card": card, "logs": parents},
        request=request,
    )

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


@login_required
@require_POST
def quill_upload(request):
    """
    Upload de imagem para o Quill (atividade).
    Retorna JSON: { url: "<url pública do arquivo>" }
    """
    f = request.FILES.get("image")
    if not f:
        return JsonResponse({"error": "Arquivo 'image' ausente."}, status=400)

    ct = (getattr(f, "content_type", "") or "").lower()
    if not ct.startswith("image/"):
        return JsonResponse({"error": "Somente imagem é permitida."}, status=400)

    try:
        if f.size and int(f.size) > 10 * 1024 * 1024:
            return JsonResponse({"error": "Imagem maior que 10MB."}, status=400)
    except Exception:
        pass

    ext = os.path.splitext(f.name or "")[1].lower()
    if ext not in [".png", ".jpg", ".jpeg", ".webp", ".gif"]:
        if ct == "image/png":
            ext = ".png"
        elif ct in ("image/jpg", "image/jpeg"):
            ext = ".jpg"
        elif ct == "image/webp":
            ext = ".webp"
        elif ct == "image/gif":
            ext = ".gif"
        else:
            ext = ".png"

    filename = f"{uuid.uuid4().hex}{ext}"
    relative_path = f"quill/{filename}"

    saved_path = default_storage.save(relative_path, f)
    url = default_storage.url(saved_path)

    return JsonResponse({"url": url})


@login_required
def cards_unread_activity(request, board_id):
    board = Board.objects.filter(id=board_id).first()
    if not board:
        return JsonResponse({"cards": {}})

    if not board.memberships.filter(user=request.user).exists():
        return JsonResponse({"cards": {}})

    seen_map = {
        cs.card_id: cs.last_seen_at
        for cs in CardSeen.objects.filter(
            user=request.user,
            card__column__board=board,
        )
    }

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


def _actor_label_and_initial(u):
    """
    Retorna (label, initial, reply_user)
    - label: @handle se existir, senão email
    - initial: primeira letra do email (ou do handle sem @)
    - reply_user: string usada no botão Responder
    """
    if not u:
        return ("(SISTEMA)", "•", "")

    handle = ""
    try:
        handle = (getattr(getattr(u, "profile", None), "handle", None) or "").strip()
    except Exception:
        handle = ""

    email = ""
    try:
        email = (getattr(u, "email", "") or "").strip()
    except Exception:
        email = ""

    if handle:
        label = f"@{handle}"
        initial = (handle[:1] or "U").upper()
        reply_user = label
        return (label, initial, reply_user)

    if email:
        label = email
        initial = (email[:1] or "U").upper()
        reply_user = email
        return (label, initial, reply_user)

    return ("(SISTEMA)", "•", "")


def _log_is_system(log) -> bool:
    """
    'System' = auditoria de ações (criou card, alterou prazo, alterou descrição etc).
    Importante: pode TER actor (ex.: "@user alterou a descrição") e ainda assim ser sistema.

    Heurística atual:
      - não é reply
      - não tem delta (atividade/quill)
      - não tem content_text (atividade/quill)
      - vem como HTML legado "audit" (normalmente com <p> e <strong>)
    """
    try:
        if getattr(log, "reply_to_id", None):
            return False
    except Exception:
        pass

    has_delta = bool(getattr(log, "content_delta", None))
    has_text = bool((getattr(log, "content_text", "") or "").strip())
    if has_delta or has_text:
        return False

    html = (getattr(log, "content", "") or "").strip().lower()
    if not html:
        return False

    # padrão clássico de auditoria: "<p><strong>...</strong> ...</p>"
    if "<p" in html and "<strong" in html:
        return True

    return False




def _log_is_files(log) -> bool:
    """
    Regra de negócio:
      - Se tem TEXTO do usuário, é comentário (mesmo que tenha imagem).
      - Se não tem texto e tem imagem/anexo, é arquivo.
    """
    txt = (getattr(log, "content_text", "") or "").strip()
    if txt:
        return False

    try:
        att = getattr(log, "attachment", None)
        if att:
            return True
    except Exception:
        pass

    html = (getattr(log, "content", "") or "").lower()

    if "<img" in html:
        return True

    for ext in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
        if ext in html:
            return True

    if ("attachments/" in html) or ("uploads/" in html) or ("/media/" in html):
        return True

    return False


def _decorate_one_log(log):
    # system
    if _log_is_system(log) or not getattr(log, "actor_id", None):
        log.cm_type = "system"
        log.cm_actor_label = "(SISTEMA)"
        log.cm_actor_initial = "•"
        log.cm_reply_user = ""
        return log

    # labels
    actor = getattr(log, "actor", None)
    label, initial, reply_user = _actor_label_and_initial(actor)
    log.cm_actor_label = label or "(usuário)"
    log.cm_actor_initial = initial or "U"
    log.cm_reply_user = reply_user or log.cm_actor_label

    # ✅ regra: se veio com delta OU texto => comments
    has_delta = bool(getattr(log, "content_delta", None))
    has_text = bool((getattr(log, "content_text", "") or "").strip())
    if has_delta or has_text:
        log.cm_type = "comments"
        return log

    # senão: heurística
    log.cm_type = "files" if _log_is_files(log) else "comments"
    return log


def _decorate_logs_for_feed(logs_qs):
    """
    Retorna LISTA (não QuerySet) com cm_* preenchido em parents e replies.
    """
    logs = list(logs_qs)
    for log in logs:
        _decorate_one_log(log)

        try:
            replies = list(getattr(log, "replies", []).all())
        except Exception:
            replies = list(getattr(log, "replies", []) or [])

        for r in replies:
            _decorate_one_log(r)

    return logs
