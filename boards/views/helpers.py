# boards/views/helpers.py

import os
import json
import base64
import re
import uuid
import requests

from django.conf import settings
from django.http import HttpResponse, JsonResponse, HttpResponseBadRequest
from django.shortcuts import render, get_object_or_404, redirect
from django.utils import timezone
from django.utils.html import escape
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count, Q
from django.urls import reverse

from ..forms import ColumnForm, CardForm, BoardForm
from ..models import (
    Board,
    Column,
    Card,
    CardLog,
    CardAttachment,
    Checklist,
    ChecklistItem,
    Organization,
    OrganizationMembership,
    BoardMembership,
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
        return escape(request.user.email or request.user.get_username() or "usuário")
    return "Sistema"


def _log_card(card: Card, request, message_html: str, attachment=None) -> None:
    """
    Registra no histórico do card (CardLog).
    message_html deve ser HTML válido.
    """
    try:
        CardLog.objects.create(
            card=card,
            content=message_html,
            attachment=attachment,
        )
    except Exception:
        # Auditoria não pode derrubar fluxo de negócio
        pass


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
    return {"card": card, "checklists": _card_checklists_qs(card)}
