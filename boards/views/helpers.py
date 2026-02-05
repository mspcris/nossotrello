# boards/views/helpers.py
import base64
import json
import logging
import os
import re
import requests
import uuid
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
from django.urls import reverse
from django.utils import timezone
from django.utils.html import escape

from boards.services.notifications import send_whatsapp
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
    Organization,
    OrganizationMembership,
    UserProfile,
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




def _log_card(card: Card, request, message_html: str, attachment=None):
    """
    Registra no histórico do card (CardLog).
    message_html deve ser HTML válido.
    Retorna a instância criada ou None.
    """
    try:
        actor = None
        if getattr(request, "user", None) and getattr(request.user, "is_authenticated", False):
            actor = request.user

        return CardLog.objects.create(
            card=card,
            actor=actor,  # ✅ passa a gravar autor quando houver
            content=message_html,
            attachment=attachment,
        )
    except Exception:
        # Auditoria não pode derrubar fluxo de negócio
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

    org, _created = Organization.objects.get_or_create(
        owner=user,
        defaults={
            "name": f"Workspace de {display_name}",
            "home_wallpaper_filename": DEFAULT_WALLPAPER_FILENAME,
        },
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

        default_storage.save(rel, ContentFile(data))
        saved.append(rel)

        url = default_storage.url(rel)
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

        subject = f"Nova marcação em: {board.name}"
        body = f"Você foi marcado por {actor_name}.\n\nQuadro: {board.name}\nCard: {card.title}\n\nLink: {url}"

        send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [to_email], fail_silently=True)
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

        # Mensagem “super hiper descontraída e cheia de ícones”
        msg = (
            "🏷️ Opa! Você foi marcado no Nosso Trello 😄✨\n"
            f"👤 Quem te marcou: {actor_name}\n"
            f"🧩 Quadro: {board.name}\n"
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






def process_mentions_and_notify(*, request, board, card, source, raw_text):
    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return

    # Cache por request (evita dupla execução dentro do mesmo request sem vazar memória)
    if not hasattr(request, "_mentions_notify_cache"):
        request._mentions_notify_cache = set()

    user_counts = _resolve_users_counts_from_mentions(raw_text or "")
    current_user_ids = set(u.id for u in user_counts.keys())

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
                # Dispara notificação (1 vez por save, sem spam)
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

    return {
        "card": card,
        "checklists": _card_checklists_qs(card),
        "board_due_colors": colors,
    }

