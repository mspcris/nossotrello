# boards/views/helpers.py
import base64
import json
import logging
import os
import re
import requests
import threading
import uuid

import bleach
from collections import Counter
from typing import List

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import Count, Q
from django.http import HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.templatetags.static import static as static_url
from django.urls import reverse
from django.utils import timezone
from django.utils.html import escape

from boards.services.notifications import (
    send_whatsapp,
    get_card_followers,
    build_card_snapshot,
    format_card_message,
    notify_users_for_card,
)

from boards.services.notifications import (
    build_card_snapshot,
    format_card_message,
    notify_users_for_card,
)

from ..models import (
    Board,
    BoardMembership,
    Card,
    CardAttachment,
    CardLog,
    Checklist,
    ChecklistItem,
    Column,
    Mention,
    NotificationBuffer,
    Organization,
    OrganizationMembership,
    UserProfile,
)




# ======================================================================
# Sanitização do HTML do Quill (anti-XSS armazenado)
# ----------------------------------------------------------------------
# O front salva `quill.root.innerHTML`. Como esse HTML é renderizado com
# |safe pra OUTROS usuários (feed de atividade, descrição do card), um POST
# forjado fora do Quill (com <script>, <img onerror>, href="javascript:")
# viraria XSS armazenado. Aqui só sobrevivem as tags/atributos que o próprio
# Quill 1.3.7 produz; o resto é descartado mantendo o texto.
# ======================================================================

_QUILL_ALLOWED_TAGS = [
    "p", "br", "span",
    "strong", "b", "em", "i", "u", "s", "del", "ins",
    "blockquote", "pre", "code",
    "ol", "ul", "li",
    "h1", "h2", "h3",
    "a", "img",
]

_QUILL_ALLOWED_ATTRS = {
    "*": ["class"],
    "a": ["href", "title", "target", "rel"],
    "img": ["src", "alt", "width", "height"],
    # tokens de @menção do quill-mention
    "span": ["class", "data-id", "data-value", "data-denotation-char", "data-index", "data-title"],
    "li": ["class", "data-list"],
    # data-cbg/data-cfg: cor de fundo/fonte do bloco de código (hex). data-attrs
    # são inertes (não executam) — a cor visual é aplicada via JS no render.
    "pre": ["class", "spellcheck", "data-cbg", "data-cfg"],
}

# javascript:, data: (exceto imagem já convertida), vbscript: ficam de fora
_QUILL_ALLOWED_PROTOCOLS = ["http", "https", "mailto", "tel"]


def sanitize_quill_html(html: str) -> str:
    """Remove qualquer tag/atributo/protocolo fora do allowlist do Quill."""
    if not html:
        return ""
    return bleach.clean(
        html,
        tags=_QUILL_ALLOWED_TAGS,
        attributes=_QUILL_ALLOWED_ATTRS,
        protocols=_QUILL_ALLOWED_PROTOCOLS,
        strip=True,
        strip_comments=True,
    )


# ======================================================================
# constantes
# ======================================================================

DEFAULT_WALLPAPER_FILENAME = "ubuntu-focal-fossa-cat-66j69z5enzbmk2m6.jpg"
DEFAULT_WALLPAPER_URL = f"/media/home_wallpapers/{DEFAULT_WALLPAPER_FILENAME}"

HOME_WALLPAPER_FOLDER = os.path.join(settings.MEDIA_ROOT, "home_wallpapers")


# ======================================================================
# AUDITORIA (CardLog)
# ======================================================================

def _actor_label(request) -> str:
    if getattr(request, "user", None) and request.user.is_authenticated:
        label = None

        # tenta usar profile (handle/display_name)
        try:
            prof = getattr(request.user, "profile", None)
        except Exception:
            prof = None

        if prof:
            if getattr(prof, "handle", None):
                label = "@" + (prof.handle or "").strip()
            elif getattr(prof, "display_name", None):
                label = (prof.display_name or "").strip()

        # fallback
        if not label:
            label = (
                (request.user.get_username() if hasattr(request.user, "get_username") else None)
                or (request.user.email or "").strip()
                or "usuário"
            )

        return escape(label)

    return "Sistema"


def _actor_html(request) -> str:
    if getattr(request, "user", None) and request.user.is_authenticated:
        u = request.user
        prof = getattr(u, "profile", None)

        handle = (getattr(prof, "handle", "") or "").strip()
        display = (getattr(prof, "display_name", "") or "").strip()

        if handle:
            url = reverse("boards:public_profile", kwargs={"handle": handle})
            title = display or u.get_full_name() or u.get_username() or u.email or ""
            return (
                f"<a class='user-link' href='{escape(url)}' "
                f"title='{escape(title)}'>@{escape(handle)}</a>"
            )

        # sem handle: mantém fallback atual (texto)
        label = display or u.get_username() or u.email or "usuário"
        return escape(label)

    return "Sistema"




def avatar_url_for(user) -> str:
    """Foto do usuário: upload > IDCamim > preset (avatar_choice) > "" (iniciais).

    Ordem definida em UserProfile.avatar_url — não duplicar aqui.
    """
    prof = getattr(user, "profile", None)
    return getattr(prof, "avatar_url", "") if prof else ""


def _person_display_name(user) -> str:
    prof = getattr(user, "profile", None)
    return (
        (getattr(prof, "display_name", "") or "").strip()
        or (user.get_full_name() or "").strip()
        or user.get_username()
        or (user.email or "").strip()
        or "Usuário"
    )


def build_impediment_previews(cards, request_user_id=None, user_is_owner=False):
    """{card_id: [ {id, name, avatar_url, is_me, can_manage}, ... ]} para os cards.

    is_me marca a pendência do próprio usuário. can_manage = is_me OU o usuário é
    dono do quadro (item 29: dono libera a pendência de qualquer um). Uma query só
    (evita N+1). Usada no board_detail e no board_poll — fonte única.
    """
    from boards.models import CardImpediment

    card_ids = [c.id for c in cards]
    out = {cid: [] for cid in card_ids}
    if not card_ids:
        return out

    qs = (
        CardImpediment.objects.filter(card_id__in=card_ids, is_active=True)
        .select_related("user", "user__profile")
        .order_by("created_at")
    )
    for imp in qs:
        is_me = imp.user_id == request_user_id
        out.setdefault(imp.card_id, []).append(
            {
                "id": imp.user_id,
                "name": _person_display_name(imp.user),
                "avatar_url": avatar_url_for(imp.user),
                "is_me": is_me,
                "can_manage": is_me or bool(user_is_owner),
            }
        )
    return out


def _log_card(card: Card, request, message_html: str, attachment=None):
    """
    Registra no histórico do card (CardLog) e enfileira notificação
    no buffer (consolidada a cada 5 min pelo flush_notifications).
    """
    try:
        actor = None
        if getattr(request, "user", None) and getattr(request.user, "is_authenticated", False):
            actor = request.user

        log = CardLog.objects.create(
            card=card,
            actor=actor,
            content=message_html,
            attachment=attachment,
        )

        # Enfileira no buffer para envio consolidado
        try:
            from django.utils.html import strip_tags as _st
            event_text = _st(message_html or "").strip()
            if len(event_text) > 490:
                event_text = event_text[:490] + "…"

            actor_name = ""
            if actor:
                prof = getattr(actor, "profile", None)
                actor_name = (
                    (getattr(prof, "display_name", "") or "").strip()
                    or actor.get_full_name()
                    or actor.get_username()
                    or ""
                )

            followers = [cf.user for cf in card.follows.select_related("user").all()]
            if actor:
                followers = [u for u in followers if u.id != actor.id]

            if followers:
                buffers = [
                    NotificationBuffer(
                        card=card,
                        recipient=u,
                        actor_name=actor_name,
                        event_summary=event_text,
                    )
                    for u in followers
                ]
                NotificationBuffer.objects.bulk_create(buffers)

        except Exception:
            # buffer nunca derruba a auditoria
            pass

        return log

    except Exception:
        return None

def _board_anchor_card(board: Board):
    """
    Para eventos de quadro/coluna sem um 'CardLog' próprio,
    escolhe um card âncora do board para registrar a auditoria (sem flood).
    """
    try:
        return (
            Card.objects.filter(column__board=board, is_deleted=False)
            .select_related("column", "column__board")
            .order_by("-updated_at", "-id")
            .first()
        )
    except Exception:
        return None


def _log_board(board: Board, request, message_html: str) -> None:
    """
    Registra evento de board/coluna no card âncora (se existir).
    """
    anchor = _board_anchor_card(board)
    if anchor:
        _log_card(anchor, request, message_html)



# ======================================================================
# HELPER – Organização "default" por usuário
# ======================================================================

def get_or_create_user_default_organization(user):
    if not user.is_authenticated:
        return None

    display_name = user.get_full_name() or user.get_username() or str(user)

    # Pode haver >1 org do mesmo owner (resquício de merge_users etc).
    # O "default" é a mais antiga (primeira criada) — consistente entre acessos.
    org = Organization.objects.filter(owner=user).order_by("id").first()
    if org is None:
        org = Organization.objects.create(
            owner=user,
            name=f"Workspace de {display_name}",
            slug=f"workspace-{user.pk}",
            home_wallpaper_filename=DEFAULT_WALLPAPER_FILENAME,
        )

    if not (getattr(org, "home_wallpaper_filename", "") or "").strip():
        org.home_wallpaper_filename = DEFAULT_WALLPAPER_FILENAME
        org.save(update_fields=["home_wallpaper_filename"])

    OrganizationMembership.objects.get_or_create(
        organization=org,
        user=user,
        defaults={"role": OrganizationMembership.Role.OWNER},
    )

    return org



# ======================================================================
# HTML/QUILL helpers
# ======================================================================

def _save_base64_images_to_media(html: str, folder: str = "quill"):
    """
    Converte TODAS <img src="data:image/...;base64,..."> em arquivos no MEDIA,
    substitui o src no HTML por /media/... e retorna:
      (html_convertido, [relative_paths_salvos])
    """
    if not html:
        return html, []

    saved = []

    pattern = re.compile(
        r'(<img[^>]+src=)(["\'])data:image\/([a-zA-Z0-9\+\-\.]+);base64,([^"\']+)\2',
        re.IGNORECASE,
    )

    def repl(m):
        prefix = m.group(1)
        quote  = m.group(2)
        fmt    = m.group(3)
        b64    = m.group(4)

        try:
            data = base64.b64decode(b64)
        except Exception:
            return m.group(0)

        ext = (fmt or "png").lower()
        if ext == "jpeg":
            ext = "jpg"

        filename = f"{uuid.uuid4().hex}.{ext}"
        rel = f"{folder}/{filename}"

        stored_name = default_storage.save(rel, ContentFile(data))
        saved.append(stored_name)

        url = default_storage.url(stored_name)
        return f"{prefix}{quote}{escape(url)}{quote}"

    new_html = pattern.sub(repl, html)
    return new_html, saved


def _ensure_attachments_and_activity_for_images(
    card: Card,
    request,
    relative_paths: list[str],
    actor: str,
    context_label: str
):
    """
    Para cada path salvo (ex: 'quill/abc.png'):
      1) garante CardAttachment (linha em Anexos)
      2) registra CardLog com preview (imagem) + nome/URL
    Faz dedupe por file.
    """
    if not relative_paths:
        return

    added_files = []

    for rel in relative_paths:
        rel = (rel or "").strip()
        if not rel:
            continue

        try:
            exists = card.attachments.filter(file=rel).exists()
        except Exception:
            exists = False

        if not exists:
            try:
                CardAttachment.objects.create(
                    card=card,
                    file=rel,
                    description=f"Imagem ({context_label})",
                )
                added_files.append(rel)
            except Exception:
                pass
        else:
            added_files.append(rel)

    try:
        parts = [f"<p><strong>{actor}</strong> adicionou imagem na <strong>{escape(context_label)}</strong>:</p>"]
        for rel in added_files:
            url = default_storage.url(rel)
            name = (rel.split("/")[-1] if rel else "imagem")
            parts.append(
                f"<div style='margin:8px 0'>"
                f"<div><a href='{escape(url)}' target='_blank' rel='noopener'>{escape(name)}</a></div>"
                f"<div style='margin-top:6px'><img src='{escape(url)}' style='max-width:100%; border-radius:8px'/></div>"
                f"</div>"
            )
        _log_card(card, request, "".join(parts))
    except Exception:
        pass




# ======================================================================
# MENTIONS helpers
# ======================================================================
# ======================================================================
# MENTIONS (Lógica de Contador/Delta)
# ======================================================================


MENTION_HANDLE_RE = re.compile(r"(?<!\w)@([a-z0-9_\.]{2,40})\b", re.IGNORECASE)
EMAIL_RE = re.compile(r"(?<![\w\.-])([A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,})(?![\w\.-])", re.IGNORECASE)

# Remove blocos HTML que carregam data-id (menção do Quill) para não contar @handle dentro deles
_QUILL_MENTION_BLOCK_RE = re.compile(
    r"<[^>]*\bdata-id=['\"]\d+['\"][^>]*>.*?</[^>]+>",
    re.IGNORECASE | re.DOTALL,
)

def _resolve_users_counts_from_mentions(text: str):
    """
    Retorna {UserInstance: count}.

    Regras:
    - Conta data-id do Quill como 1 ocorrência por elemento.
    - Evita contar o @handle que aparece dentro do HTML do Quill (senão duplica).
    - Ainda suporta menções digitadas "puras" (@handle / email) fora do Quill.
    """
    UserModel = get_user_model()
    raw = text or ""

    all_resolved_ids: list[int] = []

    # 1) data-id do Quill (fonte preferencial)
    ids = [int(x) for x in re.findall(r"data-id=['\"](\d+)['\"]", raw)]
    all_resolved_ids.extend(ids)

    # 2) Para não duplicar: remove os blocos com data-id antes de procurar @handle/email
    raw_without_quill_mentions = _QUILL_MENTION_BLOCK_RE.sub(" ", raw)

    # 3) Handles (@user) fora do Quill
    handles = [m.group(1).strip().lower() for m in MENTION_HANDLE_RE.finditer(raw_without_quill_mentions)]
    if handles:
        p_ids = UserProfile.objects.filter(handle__in=handles).values_list("user_id", flat=True)
        all_resolved_ids.extend(list(p_ids))

    # 4) Emails diretos fora do Quill
    emails = [m.group(1).strip().lower() for m in EMAIL_RE.finditer(raw_without_quill_mentions)]
    if emails:
        e_ids = UserModel.objects.filter(email__in=emails).values_list("id", flat=True)
        all_resolved_ids.extend(list(e_ids))

    counts = Counter(all_resolved_ids)
    if not counts:
        return {}

    users = UserModel.objects.filter(id__in=list(counts.keys()), is_active=True)
    return {u: counts.get(u.id, 0) for u in users if getattr(u, "email", None)}

def _send_mention_email(request, mentioned_user, actor_user, board, card, mention):
    """
    Dispara o e-mail de notificação.
    """
    try:
        to_email = (getattr(mentioned_user, "email", "") or "").strip()
        if not to_email: return

        actor_name = (getattr(actor_user, "profile", None) and 
                     (actor_user.profile.display_name or actor_user.profile.handle)) or \
                     actor_user.get_full_name() or actor_user.get_username()

        path = reverse("boards:board_detail", kwargs={"board_id": board.id})
        url = request.build_absolute_uri(f"{path}?card={card.id}&tab=ativ&mention={mention.id}")

        column_name = getattr(getattr(card, "column", None), "name", "") or ""
        subject = f"'{actor_name}' marcou você no card: '{card.title}'"
        body = (
            f"Você foi marcado por {actor_name}.\n\n"
            f"Quadro: {board.name}\n"
            f"Coluna: {column_name}\n"
            f"Card: {card.title}\n\n"
            f"Link: {url}"
        )

        threading.Thread(
            target=send_mail,
            args=(subject, body, settings.DEFAULT_FROM_EMAIL, [to_email]),
            kwargs={"fail_silently": True},
            daemon=True,
        ).start()
    except Exception:
        pass



logger = logging.getLogger(__name__)

def _send_mention_whatsapp(request, mentioned_user, actor_user, board, card, mention):
    """
    Dispara WhatsApp de notificação de marcação (duas mensagens: texto + link).
    Respeita preferência do usuário (notify_whatsapp) e valida telefone.
    """
    try:
        prof = getattr(mentioned_user, "profile", None)
        if not prof or not getattr(prof, "notify_whatsapp", False):
            return

        phone_raw = (getattr(prof, "telefone", "") or "").strip()
        phone_digits = re.sub(r"\D+", "", phone_raw)

        # Se não tiver DDI, assume BR
        if len(phone_digits) in (10, 11):
            phone_digits = "55" + phone_digits

        # Valida: 55 + DDD + (8 ou 9)
        if len(phone_digits) not in (12, 13):
            logger.warning(
                "mention_whatsapp: invalid phone user_id=%s raw=%r digits=%r",
                getattr(mentioned_user, "id", None), phone_raw, phone_digits
            )
            return

        actor_name = (
            (getattr(actor_user, "profile", None) and (actor_user.profile.display_name or actor_user.profile.handle))
            or actor_user.get_full_name()
            or actor_user.get_username()
            or (actor_user.email or "alguém")
        )
        actor_name = (actor_name or "").strip()

        # Link igual ao e-mail (tab=ativ&mention=...)
        path = reverse("boards:board_detail", kwargs={"board_id": board.id})
        url = request.build_absolute_uri(f"{path}?card={card.id}&tab=ativ&mention={mention.id}")

        column_name = getattr(getattr(card, "column", None), "name", "") or ""

        # Mensagem "super hiper descontraída e cheia de ícones"
        msg = (
            "🏷️ Opa! Você foi marcado no Nosso Trello 😄✨\n"
            f"👤 Quem te marcou: {actor_name}\n"
            f"🧩 Quadro: {board.name}\n"
            f"📂 Coluna: {column_name}\n"
            f"🗂️ Card: {card.title}\n"
            "🔥 Bora dar uma olhada? 👇👀"
        )

        send_whatsapp(user=mentioned_user, phone_digits=phone_digits, body=msg)
        send_whatsapp(user=mentioned_user, phone_digits=phone_digits, body=url)

    except Exception:
        # Não derruba fluxo
        logger.exception(
            "mention_whatsapp: send failed user_id=%s board_id=%s card_id=%s",
            getattr(mentioned_user, "id", None),
            getattr(board, "id", None),
            getattr(card, "id", None),
        )
        return






def _get_mention_notify_plan(mentioned_user) -> dict:
    """Verifica quais canais serão usados para este usuário ANTES de enviar."""
    prof = getattr(mentioned_user, "profile", None)
    name = (
        (prof and (getattr(prof, "display_name", "") or getattr(prof, "handle", "")))
        or getattr(mentioned_user, "get_full_name", lambda: "")()
        or getattr(mentioned_user, "username", "?")
    )
    name = (name or "?").strip()

    to_email = (getattr(mentioned_user, "email", "") or "").strip()
    will_email = bool(to_email) and bool(getattr(prof, "notify_email", True) if prof else True)

    phone_raw = (getattr(prof, "telefone", "") or "").strip() if prof else ""
    phone_digits = re.sub(r"\D+", "", phone_raw)
    if len(phone_digits) in (10, 11):
        phone_digits = "55" + phone_digits
    will_whatsapp = (
        bool(getattr(prof, "notify_whatsapp", False) if prof else False)
        and len(phone_digits) in (12, 13)
    )

    return {"name": name, "email": will_email, "whatsapp": will_whatsapp}


def build_notify_toast_html(plans: list) -> str:
    """Retorna snippet OOB HTMX que injeta um toast em #nt-toast-container."""
    if not plans:
        return ""
    lines = []
    for p in plans:
        channels = []
        if p.get("whatsapp"):
            channels.append("WhatsApp")
        if p.get("email"):
            channels.append("Email")
        if channels:
            lines.append(f"{p.get('name', '?')} via {' e '.join(channels)}")
    if not lines:
        return ""
    lines_html = "".join(f'<div class="nt-toast-line">{l}</div>' for l in lines)
    return (
        '<div hx-swap-oob="beforeend:#nt-toast-container">'
        '<div class="nt-toast">'
        '<div class="nt-toast-title">🔔 Notificação enviada</div>'
        f'{lines_html}'
        '</div>'
        '</div>'
    )


def process_mentions_and_notify(*, request, board, card, source, raw_text):
    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return []

    # Cache por request (evita dupla execução dentro do mesmo request sem vazar memória)
    if not hasattr(request, "_mentions_notify_cache"):
        request._mentions_notify_cache = set()

    user_counts = _resolve_users_counts_from_mentions(raw_text or "")
    current_user_ids = set(u.id for u in user_counts.keys())
    notify_plans = []

    with transaction.atomic():
        # 1) Trata usuários que EXISTIAM antes e foram REMOVIDOS completamente no texto
        #    => zera baseline para permitir que uma futura re-marcação dispare
        stale_qs = (
            Mention.objects.select_for_update()
            .filter(card=card, source=source)
            .exclude(mentioned_user_id__in=current_user_ids)
        )
        for m in stale_qs:
            # Se não está mais no texto, baseline vira 0
            if m.seen_count != 0 or m.emailed_count != 0:
                m.seen_count = 0
                m.emailed_count = 0
                m.raw_text = (raw_text or "")[:5000]
                m.save(update_fields=["seen_count", "emailed_count", "raw_text"])

        # 2) Processa usuários presentes no texto atual
        for mentioned_user, current_total in user_counts.items():
            if mentioned_user == request.user:
                continue

            cache_key = (card.id, mentioned_user.id, source)
            if cache_key in request._mentions_notify_cache:
                continue

            mention_obj, created = Mention.objects.select_for_update().get_or_create(
                card=card,
                mentioned_user=mentioned_user,
                source=source,
                defaults={
                    "board": board,
                    "actor": request.user,
                    "seen_count": 0,
                    "emailed_count": 0,
                    "raw_text": (raw_text or "")[:5000],
                },
            )

            if not created:
                mention_obj.refresh_from_db()

            # 2.1 Se houve remoção parcial (queda), rebaixa baseline
            # Ex.: tinha 2 enviados, apagou para 1 => emailed_count deve virar 1
            if current_total < mention_obj.seen_count:
                mention_obj.emailed_count = min(mention_obj.emailed_count, current_total)

                       # 2.2 Delta: se current_total > emailed_count => manda (geralmente 1)
            if current_total > mention_obj.emailed_count:
                # Regra: mention => usuário passa a seguir o card a partir daqui
                try:
                    from boards.models import CardFollow
                    CardFollow.objects.get_or_create(card=card, user=mentioned_user)
                except Exception:
                    # seguir não pode quebrar fluxo de comentário
                    pass

                # Coleta plano ANTES de enviar (sincrono e rapido)
                plan = _get_mention_notify_plan(mentioned_user)
                if plan.get("email") or plan.get("whatsapp"):
                    notify_plans.append(plan)

                # Dispara notificação (1 vez por save, sem spam) — ambas já assíncronas
                _send_mention_email(request, mentioned_user, request.user, board, card, mention_obj)
                _send_mention_whatsapp(request, mentioned_user, request.user, board, card, mention_obj)

                mention_obj.emailed_count = current_total



            # 2.3 Sempre atualiza seen_count e raw_text
            mention_obj.seen_count = current_total
            mention_obj.raw_text = (raw_text or "")[:5000]
            mention_obj.actor = request.user
            mention_obj.board = board
            mention_obj.save(update_fields=["seen_count", "emailed_count", "raw_text", "actor", "board"])

            request._mentions_notify_cache.add(cache_key)

    return notify_plans





# ======================================================================
# Save e disponibilizar de imagens do HTML (quill)
# ======================================================================



def _extract_media_image_paths(html: str, folder: str = "quill") -> list[str]:
    """
    Extrai paths relativos (ex: 'quill/abc.png') de <img src="/media/...">.
    Filtra apenas os que começam com '{folder}/'.
    """
    if not html:
        return []

    media_url = (getattr(settings, "MEDIA_URL", "/media/") or "/media/").rstrip("/") + "/"
    # pega src="..."
    srcs = re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', html, flags=re.IGNORECASE)

    rels = []
    for src in srcs:
        if not src:
            continue

        # normaliza: aceita "/media/..." e também "http(s)://.../media/..."
        idx = src.find(media_url)
        if idx == -1:
            continue

        rel = src[idx + len(media_url):].lstrip("/")
        if not rel:
            continue

        if folder and not rel.startswith(folder.rstrip("/") + "/"):
            continue

        rels.append(rel)

    # dedupe preservando ordem
    seen = set()
    out = []
    for r in rels:
        if r in seen:
            continue
        seen.add(r)
        out.append(r)
    return out

# ======================================================================
# Permissões (board)
# ======================================================================

def _can_view_board(request, board: Board) -> bool:
    if not request.user.is_authenticated:
        return False
    if request.user.is_staff:
        return True

    memberships_qs = board.memberships.all()
    if memberships_qs.exists():
        return memberships_qs.filter(user=request.user).exists()

    return bool(board.created_by_id == request.user.id)


def _can_edit_board(request, board: Board) -> bool:
    if not request.user.is_authenticated:
        return False
    if request.user.is_staff:
        return True

    memberships_qs = board.memberships.all()
    if memberships_qs.exists():
        return memberships_qs.filter(
            user=request.user,
            role__in=[BoardMembership.Role.OWNER, BoardMembership.Role.EDITOR],
        ).exists()

    return bool(board.created_by_id == request.user.id)


# ======================================================================
# Modal helpers
# ======================================================================

def _card_checklists_qs(card: Card):
    return (
        card.checklists
        .annotate(
            total=Count("items"),
            done=Count("items", filter=Q(items__is_done=True)),
        )
        .prefetch_related("items")
        .order_by("position", "created_at")
    )


def _card_modal_context(card: Card) -> dict:
    board = card.column.board

    # cores padrão do board (fallback determinístico)
    colors = getattr(board, "due_colors", None) or {}
    if not isinstance(colors, dict):
        colors = {}

    # defaults
    colors.setdefault("ok", "#16a34a")       # verde
    colors.setdefault("warn", "#f59e0b")     # amarelo
    colors.setdefault("overdue", "#dc2626")  # vermelho

    # Impedimento: membros do board (candidatos a responsável) + quem já trava
    imp_members = []
    imp_active_ids = []
    try:
        from boards.models import CardImpediment

        imp_active_ids = list(
            CardImpediment.objects.filter(card=card, is_active=True).values_list("user_id", flat=True)
        )
        for u in _board_member_users(board):
            imp_members.append(
                {
                    "id": u.id,
                    "name": _person_display_name(u),
                    "avatar_url": avatar_url_for(u),
                    "is_responsible": u.id in imp_active_ids,
                }
            )
    except Exception:
        pass

    # imagem de capa preservada (para o swatch "restaurar imagem")
    cover_prev_url = ""
    prev = (getattr(card, "cover_prev_path", "") or "").strip()
    if prev:
        try:
            from django.core.files.storage import default_storage
            cover_prev_url = default_storage.url(prev)
        except Exception:
            cover_prev_url = ""

    return {
        "card": card,
        "checklists": _card_checklists_qs(card),
        "board_due_colors": colors,
        "impediment_members": imp_members,
        "impediment_active_ids": imp_active_ids,
        "cover_prev_url": cover_prev_url,
    }


def _user_secret_label(u) -> str:
    """Rótulo amigável p/ a lista de 'quem pode ver': @handle > nome > email."""
    if not u:
        return ""
    prof = getattr(u, "profile", None)
    handle = (getattr(prof, "handle", "") or "").strip()
    if handle:
        return "@" + handle
    display = (getattr(prof, "display_name", "") or "").strip()
    if display:
        return display
    full = (u.get_full_name() or "").strip() if hasattr(u, "get_full_name") else ""
    if full:
        return full
    return (getattr(u, "email", "") or getattr(u, "username", "") or "").strip()


def _board_member_users(board) -> list:
    """
    Usuários candidatos a viewer de um segredo: membros do board (ou o criador,
    nos boards legados sem memberships). Ordenados por rótulo.
    """
    User = get_user_model()
    users = []

    memberships = (
        board.memberships.select_related("user").all() if board else []
    )
    if memberships:
        users = [m.user for m in memberships if m.user]
    elif board and board.created_by_id:
        u = User.objects.filter(id=board.created_by_id).first()
        if u:
            users.append(u)

    seen, out = set(), []
    for u in users:
        if u.id in seen:
            continue
        seen.add(u.id)
        out.append(u)

    out.sort(key=lambda u: (_user_secret_label(u) or "").lower())
    return out


def _card_secret_context(card, user) -> dict:
    """
    Monta o contexto da seção 'Códigos compartilhados' do modal:
    - card_secrets: segredos ativos, anotados com _can_reveal/_viewer_count.
    - secret_candidates: membros do board (menos o próprio user) p/ os checkboxes.
    """
    secrets = (
        card.secrets.filter(is_active=True)
        .select_related("author", "author__profile")
        .prefetch_related("viewers")
        .order_by("-created_at")
    )

    decorated = []
    for s in secrets:
        # nomes sem underscore inicial — templates Django não acessam _attr
        s.cm_can_reveal = s.can_reveal(user)
        viewers = list(s.viewers.all())
        s.cm_viewer_count = len(viewers)
        s.cm_viewer_ids = {u.id for u in viewers}
        s.cm_viewer_labels = [_user_secret_label(u) for u in viewers]
        s.cm_is_author = bool(s.author_id and s.author_id == getattr(user, "id", None))
        decorated.append(s)

    board = card.column.board if card.column_id else None
    uid = getattr(user, "id", None)
    candidates = [
        {"id": u.id, "label": _user_secret_label(u)}
        for u in _board_member_users(board)
        if u.id != uid
    ]

    # O autor SEMPRE pode revelar (ver CardSecret.can_reveal). Expomos ele como
    # uma entrada fixa/marcada na UI pra deixar claro que dá pra guardar um
    # segredo só pra si mesmo (ex.: senha pessoal) — não precisa marcar ninguém.
    secret_self = {"id": uid, "label": _user_secret_label(user)} if uid else None

    return {
        "card_secrets": decorated,
        "secret_candidates": candidates,
        "secret_self": secret_self,
    }

