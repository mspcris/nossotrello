# ======================================================================
# IMPORTAÇÕES
# ======================================================================

import os
import json
import base64
import re
import uuid
import requests

from urllib.parse import parse_qs

from django.conf import settings
from django.shortcuts import render, get_object_or_404, redirect
from django.http import HttpResponse, JsonResponse, HttpResponseBadRequest
from django.views.decorators.http import require_POST, require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.db import transaction
from django.utils import timezone
from django.utils.html import escape
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth import get_user_model
from django.db.models import Count, Q
from django.urls import reverse

from .forms import ColumnForm, CardForm, BoardForm
from .models import (
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
# HELPERS – HTML / imagens base64
# ======================================================================

def extract_base64_and_convert(html_content):
    """
    Extrai a PRIMEIRA imagem base64 do HTML e devolve:
      - html limpo (removendo o <img ...> inteiro)
      - ContentFile (arquivo) ou None
    """
    if not html_content:
        return html_content, None

    pattern = r'<img[^>]+src="data:image\/([a-zA-Z]+);base64,([^"]+)"[^>]*>'
    match = re.search(pattern, html_content)

    if not match:
        return html_content, None

    image_format = match.group(1)
    base64_str = match.group(2)

    try:
        image_data = base64.b64decode(base64_str)
    except Exception:
        return html_content, None

    filename = f"upload.{image_format}"
    file_obj = ContentFile(image_data, name=filename)

    cleaned_html = re.sub(pattern, "", html_content, count=1)
    return cleaned_html, file_obj


def strip_img_tags(html):
    if not html:
        return html
    # Remove APENAS imagens base64 (pesadas). Preserva <img src="/media/...">
    return re.sub(
        r'<img[^>]+src="data:image\/[^"]+"[^>]*>',
        "",
        html,
        flags=re.IGNORECASE,
    )


def _card_has_cover_image(card: Card) -> bool:
    return hasattr(card, "cover_image")


def _set_cover_from_file(card: Card, extracted_file: ContentFile) -> bool:
    """
    Tenta setar cover_image se existir no model.
    Retorna True se setou, False se não existe/indisponível.
    """
    if not extracted_file or not _card_has_cover_image(card):
        return False

    try:
        card.cover_image.save(extracted_file.name, extracted_file, save=False)
        return True
    except Exception:
        return False


def _set_cover_from_relative_path(card: Card, relative_path: str) -> bool:
    if not relative_path or not _card_has_cover_image(card):
        return False
    try:
        card.cover_image.name = relative_path
        card.save(update_fields=["cover_image"])
        return True
    except Exception:
        return False


# ======================================================================
# HOME (lista de boards)
# ======================================================================

def index(request):
    if request.user.is_authenticated:
        qs = BoardMembership.objects.filter(
            user=request.user,
            board__is_deleted=False,
        ).select_related("board")

        owned_ids = list(qs.filter(role=BoardMembership.Role.OWNER).values_list("board_id", flat=True))
        shared_ids = list(qs.exclude(role=BoardMembership.Role.OWNER).values_list("board_id", flat=True))

        owned_boards = (
            Board.objects.filter(id__in=owned_ids, is_deleted=False)
            .distinct()
            .order_by("-created_at")
        )

        shared_boards = (
            Board.objects.filter(id__in=shared_ids, is_deleted=False)
            .distinct()
            .order_by("-created_at")
        )

        # Dono do board (para exibir na Home em "Compartilhados comigo")
        owner_by_board = {}
        if shared_ids:
            owner_memberships = (
                BoardMembership.objects.filter(
                    board_id__in=shared_ids,
                    role=BoardMembership.Role.OWNER,
                )
                .select_related("user")
            )
            for m in owner_memberships:
                if m.board_id not in owner_by_board:
                    owner_by_board[m.board_id] = m.user

        for b in shared_boards:
            u = owner_by_board.get(b.id)
            b.owner_email = (u.email or u.get_username()) if u else ""

    else:
        owned_boards = Board.objects.filter(is_deleted=False).order_by("-created_at")
        shared_boards = Board.objects.none()

    home_bg_image = None
    if request.user.is_authenticated:
        org = get_or_create_user_default_organization(request.user)
        filename = (getattr(org, "home_wallpaper_filename", "") or "").strip()
        if filename:
            home_bg_image = filename

    return render(
        request,
        "boards/index.html",
        {
            "owned_boards": owned_boards,
            "shared_boards": shared_boards,
            "home_bg": True,
            "home_bg_image": home_bg_image,
        },
    )


# ======================================================================
# DETALHE DE UM BOARD
# ======================================================================

def board_detail(request, board_id):
    board = get_object_or_404(Board, id=board_id, is_deleted=False)

    memberships_qs = board.memberships.select_related("user")

    my_membership = None
    can_leave_board = False
    can_share_board = False

    if memberships_qs.exists():
        if not request.user.is_authenticated:
            return HttpResponse("Você não tem acesso a este quadro.", status=403)

        my_membership = memberships_qs.filter(user=request.user).first()
        if not my_membership:
            return HttpResponse("Você não tem acesso a este quadro.", status=403)

        can_share_board = (my_membership.role == BoardMembership.Role.OWNER)

        if my_membership.role != BoardMembership.Role.OWNER:
            can_leave_board = True
        else:
            owners_count = memberships_qs.filter(role=BoardMembership.Role.OWNER).count()
            can_leave_board = owners_count > 1

    else:
        if request.user.is_authenticated and (board.created_by_id == request.user.id or request.user.is_staff):
            can_share_board = True

    columns = board.columns.filter(is_deleted=False).order_by("position")
    return render(
        request,
        "boards/board_detail.html",
        {
            "board": board,
            "columns": columns,
            "my_membership": my_membership,
            "can_leave_board": can_leave_board,
            "can_share_board": can_share_board,
        },
    )


# ======================================================================
# SAIR DA BOARD
# ======================================================================

@require_POST
def board_leave(request, board_id):
    if not request.user.is_authenticated:
        return HttpResponse("Login necessário.", status=401)

    board = get_object_or_404(Board, id=board_id, is_deleted=False)

    membership = BoardMembership.objects.filter(board=board, user=request.user).first()
    if not membership:
        return HttpResponse("Você não tem acesso a este quadro.", status=403)

    if membership.role == BoardMembership.Role.OWNER:
        owners_count = BoardMembership.objects.filter(board=board, role=BoardMembership.Role.OWNER).count()
        if owners_count <= 1:
            return HttpResponse("Você é o último DONO do quadro e não pode sair.", status=400)

    actor = _actor_label(request)
    membership.delete()

    _log_board(
        board,
        request,
        f"<p><strong>{actor}</strong> saiu do quadro <strong>{escape(board.name)}</strong>.</p>",
    )

    redirect_url = reverse("boards:boards_index")

    if request.headers.get("HX-Request") == "true":
        resp = HttpResponse("")
        resp["HX-Redirect"] = redirect_url
        return resp

    return redirect(redirect_url)


# ======================================================================
# ADICIONAR COLUNA
# ======================================================================

def add_column(request, board_id):
    board = get_object_or_404(Board, id=board_id)

    if request.method == "POST":
        form = ColumnForm(request.POST)
        if form.is_valid():
            column = form.save(commit=False)
            column.board = board
            column.position = board.columns.count()
            column.save()

            actor = _actor_label(request)
            _log_board(
                board,
                request,
                f"<p><strong>{actor}</strong> criou a coluna <strong>{escape(column.name)}</strong> no quadro <strong>{escape(board.name)}</strong>.</p>",
            )

            return render(request, "boards/partials/column_item.html", {"column": column})

        return HttpResponse("Erro ao criar coluna.", status=400)

    return render(
        request,
        "boards/partials/add_column_form.html",
        {"board": board, "form": ColumnForm()},
    )


# ======================================================================
# DEFINIR TEMA DA COLUNA
# ======================================================================

@require_POST
def set_column_theme(request, column_id):
    column = get_object_or_404(Column, id=column_id)
    theme = request.POST.get("theme")

    valid_themes = [t[0] for t in Column.THEME_CHOICES]
    if theme not in valid_themes:
        return HttpResponse("Tema inválido", status=400)

    old_theme = getattr(column, "theme", "")
    column.theme = theme
    column.save(update_fields=["theme"])

    actor = _actor_label(request)
    _log_board(
        column.board,
        request,
        f"<p><strong>{actor}</strong> alterou o tema da coluna <strong>{escape(column.name)}</strong> de <strong>{escape(old_theme)}</strong> para <strong>{escape(theme)}</strong>.</p>",
    )

    return render(request, "boards/partials/column_item.html", {"column": column})


# ======================================================================
# REORDENAR COLUNAS
# ======================================================================

@login_required
@require_POST
def reorder_columns(request, board_id):
    board = get_object_or_404(Board, id=board_id, is_deleted=False)

    try:
        payload = json.loads(request.body.decode("utf-8"))
        order = payload.get("order", [])
        if not isinstance(order, list):
            return JsonResponse({"ok": False, "error": "order inválido"}, status=400)
        order = [int(x) for x in order]
    except Exception:
        return JsonResponse({"ok": False, "error": "JSON inválido"}, status=400)

    cols = Column.objects.filter(board=board, is_deleted=False)
    cols_map = {c.id: c for c in cols}

    if any(cid not in cols_map for cid in order):
        return JsonResponse({"ok": False, "error": "coluna fora do board"}, status=400)

    with transaction.atomic():
        for idx, cid in enumerate(order):
            Column.objects.filter(id=cid, board=board).update(position=idx)

    actor = _actor_label(request)
    _log_board(
        board,
        request,
        f"<p><strong>{actor}</strong> reordenou colunas no quadro <strong>{escape(board.name)}</strong>.</p>",
    )

    return JsonResponse({"ok": True})


# ======================================================================
# ADICIONAR CARD
# ======================================================================

def add_card(request, column_id):
    column = get_object_or_404(Column, id=column_id)

    if request.method == "POST":
        form = CardForm(request.POST)
        if not form.is_valid():
            return HttpResponse("Erro ao criar card.", status=400)

        card = form.save(commit=False)

        raw_desc = (request.POST.get("description") or card.description or "")
        clean_desc, extracted_file = extract_base64_and_convert(raw_desc)

        # se não veio base64, tenta pegar a primeira <img src="/media/...">
        if not extracted_file:
            m = re.search(r'<img[^>]+src="([^"]+)"', raw_desc or "")
            if m:
                url = (m.group(1) or "").strip()
                if "/media/" in url:
                    relative_path = url.split("/media/")[-1].strip()
                    if relative_path:
                        _set_cover_from_relative_path(card, relative_path)

        # descrição sem base64 pesado
        card.description = strip_img_tags(clean_desc)

        # capa via base64 (se existir)
        _set_cover_from_file(card, extracted_file)

        card.column = column
        card.position = column.cards.count()
        card.save()

        actor = _actor_label(request)
        _log_card(
            card,
            request,
            f"<p><strong>{actor}</strong> criou este card na coluna <strong>{escape(column.name)}</strong>.</p>",
        )

        if _card_has_cover_image(card) and getattr(card, "cover_image", None) and card.cover_image:
            _log_card(card, request, f"<p><strong>{actor}</strong> definiu uma capa na criação do card.</p>")

        return render(request, "boards/partials/card_item.html", {"card": card})

    return render(
        request,
        "boards/partials/add_card_form.html",
        {"column": column, "form": CardForm()},
    )


# ======================================================================
# ADICIONAR BOARD
# ======================================================================

def add_board(request):
    if request.method == "POST":
        form = BoardForm(request.POST)
        if not form.is_valid():
            return HttpResponse("Erro ao criar board", status=400)

        board = form.save(commit=False)

        if request.user.is_authenticated:
            board.created_by = request.user
            board.organization = get_or_create_user_default_organization(request.user)

        board.save()

        if request.user.is_authenticated:
            BoardMembership.objects.get_or_create(
                board=board,
                user=request.user,
                defaults={"role": BoardMembership.Role.OWNER},
            )

        actor = _actor_label(request)
        _log_board(
            board,
            request,
            f"<p><strong>{actor}</strong> criou o quadro <strong>{escape(board.name)}</strong>.</p>",
        )

        return HttpResponse(f'<script>window.location.href="/board/{board.id}/"</script>')

    return render(request, "boards/partials/add_board_form.html", {"form": BoardForm()})


# ======================================================================
# SOFT DELETE DE BOARD
# ======================================================================

def delete_board(request, board_id):
    if request.method != "POST":
        return HttpResponseBadRequest("Método inválido.")

    try:
        board = Board.objects.get(id=board_id, is_deleted=False)
    except Board.DoesNotExist:
        return HttpResponseBadRequest("Quadro não encontrado.")

    actor = _actor_label(request)

    # log no âncora antes de apagar
    _log_board(
        board,
        request,
        f"<p><strong>{actor}</strong> excluiu (soft delete) o quadro <strong>{escape(board.name)}</strong>.</p>",
    )

    now = timezone.now()
    board.is_deleted = True
    board.deleted_at = now
    board.save(update_fields=["is_deleted", "deleted_at"])

    Column.objects.filter(board=board, is_deleted=False).update(is_deleted=True, deleted_at=now)
    Card.objects.filter(column__board=board, is_deleted=False).update(is_deleted=True, deleted_at=now)

    return HttpResponse("")


# ======================================================================
# EDITAR CARD (modal antigo)
# ======================================================================

def edit_card(request, card_id):
    card = get_object_or_404(Card, id=card_id)

    if request.method == "POST":
        form = CardForm(request.POST, request.FILES, instance=card)
        if form.is_valid():
            form.save()

            actor = _actor_label(request)
            _log_card(card, request, f"<p><strong>{actor}</strong> editou o card (modal antigo).</p>")

            return render(request, "boards/partials/card_modal_body.html", {"card": card})
    else:
        form = CardForm(instance=card)

    return render(request, "boards/partials/card_edit_form.html", {"card": card, "form": form})


# ======================================================================
# ATUALIZAR CARD (modal novo)
# ======================================================================

@require_POST
def update_card(request, card_id):
    card = get_object_or_404(Card, id=card_id)

    actor = _actor_label(request)

    old_title = card.title
    old_desc = card.description or ""
    old_tags_raw = card.tags or ""

    # título
    card.title = request.POST.get("title", card.title)

    # descrição (HTML do Quill)
    raw_desc = request.POST.get("description", card.description or "")

    # base64 -> arquivo
    clean_desc, extracted_file = extract_base64_and_convert(raw_desc)

    # regra: descrição nunca guarda base64
    clean_desc = strip_img_tags(clean_desc)
    card.description = clean_desc

    # capa via base64 (se existir)
    cover_changed = _set_cover_from_file(card, extracted_file)

    # tags
    new_tags_raw = request.POST.get("tags", old_tags_raw) or ""

    old_tags = [t.strip() for t in old_tags_raw.split(",") if t.strip()]
    new_tags = [t.strip() for t in new_tags_raw.split(",") if t.strip()]

    card.tags = new_tags_raw
    removed = [t for t in old_tags if t not in new_tags]
    added = [t for t in new_tags if t not in old_tags]

    card.save()

    # logs
    if removed:
        for t in removed:
            _log_card(card, request, f"<p><strong>{actor}</strong> removeu a etiqueta <strong>{escape(t)}</strong>.</p>")
    if added:
        for t in added:
            _log_card(card, request, f"<p><strong>{actor}</strong> adicionou a etiqueta <strong>{escape(t)}</strong>.</p>")

    if (old_desc or "").strip() != (card.description or "").strip():
        _log_card(card, request, f"<p><strong>{actor}</strong> atualizou a descrição.</p>")

    if (old_title or "").strip() != (card.title or "").strip():
        _log_card(
            card,
            request,
            f"<p><strong>{actor}</strong> alterou o título de <strong>{escape(old_title)}</strong> para <strong>{escape(card.title)}</strong>.</p>",
        )

    if cover_changed:
        _log_card(card, request, f"<p><strong>{actor}</strong> atualizou a capa do card.</p>")

    # fallback (se nada foi detectado)
    if not (removed or added or cover_changed or (old_desc.strip() != (card.description or "").strip()) or (old_title.strip() != card.title.strip())):
        _log_card(card, request, f"<p><strong>{actor}</strong> atualizou o card.</p>")

    return render(request, "boards/partials/card_modal_body.html", {"card": card})


# ======================================================================
# ATUALIZAR CARD_COVER (colar URL /media/)
# ======================================================================

@require_POST
def set_card_cover(request, card_id):
    card = get_object_or_404(Card, id=card_id)
    actor = _actor_label(request)

    # 1) tenta via POST normal
    url = (
        (request.POST.get("url") or "").strip()
        or (request.POST.get("src") or "").strip()
        or (request.POST.get("image_url") or "").strip()
        or (request.POST.get("cover_url") or "").strip()
        or (request.POST.get("path") or "").strip()
        or (request.POST.get("file_url") or "").strip()
    )

    # 2) tenta JSON
    if not url and request.body:
        try:
            data = json.loads(request.body.decode("utf-8"))
            url = (
                (data.get("url") or "").strip()
                or (data.get("src") or "").strip()
                or (data.get("image_url") or "").strip()
                or (data.get("cover_url") or "").strip()
                or (data.get("path") or "").strip()
                or (data.get("file_url") or "").strip()
            )
        except Exception:
            pass

    # 3) tenta body cru
    if not url and request.body:
        raw = request.body.decode("utf-8", errors="ignore").strip()
        if raw.startswith("/media/") or raw.startswith("http"):
            url = raw
        else:
            parsed = parse_qs(raw)
            for k in ("url", "src", "image_url", "cover_url", "path", "file_url"):
                if k in parsed and parsed[k]:
                    url = (parsed[k][0] or "").strip()
                    if url:
                        break

    if not url:
        return HttpResponse("URL inválida", status=400)

    if url.startswith("/media/"):
        relative_path = url.split("/media/")[-1].strip()
    elif "/media/" in url:
        relative_path = url.split("/media/")[-1].strip()
    else:
        return HttpResponse("URL precisa apontar para /media/", status=400)

    if not relative_path:
        return HttpResponse("Caminho inválido", status=400)

    ok = _set_cover_from_relative_path(card, relative_path)
    if not ok:
        return HttpResponse("Falha ao definir capa.", status=400)

    file_url = default_storage.url(relative_path)

    _log_card(
        card,
        request,
        (
            f"<p><strong>{actor}</strong> definiu a imagem como capa.</p>"
            f'<p><img src="{escape(file_url)}" /></p>'
        ),
    )

    return render(request, "boards/partials/card_modal_body.html", {"card": card})


@require_POST
def remove_card_cover(request, card_id):
    card = get_object_or_404(Card, id=card_id)
    actor = _actor_label(request)

    if not _card_has_cover_image(card):
        return HttpResponse("cover_image não configurado no model Card.", status=400)

    if card.cover_image:
        card.cover_image = None
        card.save(update_fields=["cover_image"])
        _log_card(card, request, f"<p><strong>{actor}</strong> removeu a capa do card.</p>")

    return render(request, "boards/partials/card_modal_body.html", {"card": card})




# ======================================================================
# ETIQUETAS COLORIDAS CLICAVEIS
# ======================================================================

@require_POST
def set_tag_color(request, card_id):
    card = get_object_or_404(Card, id=card_id)
    tag = (request.POST.get("tag") or "").strip()
    color = (request.POST.get("color") or "").strip()

    if not tag:
        return HttpResponse("Tag inválida", status=400)

    # valida hex simples (#RRGGBB)
    if not re.match(r"^#[0-9a-fA-F]{6}$", color):
        return HttpResponse("Cor inválida", status=400)

    try:
        data = json.loads(card.tag_colors or "{}")
        if not isinstance(data, dict):
            data = {}
    except Exception:
        data = {}

    data[tag] = color
    card.tag_colors = json.dumps(data, ensure_ascii=False)
    card.save(update_fields=["tag_colors"])

    # retorna só a barra de tags para o HTMX trocar
    return render(request, "boards/partials/card_tags_bar.html", {"card": card})





# ======================================================================
# DELETAR CARD (soft delete)
# ======================================================================

@require_POST
def delete_card(request, card_id):
    card = get_object_or_404(Card.all_objects, id=card_id)
    actor = _actor_label(request)

    if not card.is_deleted:
        _log_card(card, request, f"<p><strong>{actor}</strong> excluiu (soft delete) este card.</p>")
        card.is_deleted = True
        card.deleted_at = timezone.now()
        card.save(update_fields=["is_deleted", "deleted_at"])

    return HttpResponse("", status=200)


# ======================================================================
# DELETAR COLUNA (soft delete + soft delete dos cards)
# ======================================================================

def delete_column(request, column_id):
    if request.method != "POST":
        return HttpResponseBadRequest("Método inválido.")

    try:
        column = Column.objects.get(id=column_id, is_deleted=False)
    except Column.DoesNotExist:
        return HttpResponseBadRequest("Coluna não encontrada.")

    actor = _actor_label(request)

    # loga em todos cards (pecar por excesso) antes do soft delete
    cards_in_col = Card.objects.filter(column=column, is_deleted=False)
    for c in cards_in_col:
        _log_card(
            c,
            request,
            f"<p><strong>{actor}</strong> excluiu (soft delete) a coluna <strong>{escape(column.name)}</strong>, removendo este card da visualização.</p>",
        )

    _log_board(
        column.board,
        request,
        f"<p><strong>{actor}</strong> excluiu (soft delete) a coluna <strong>{escape(column.name)}</strong>.</p>",
    )

    now = timezone.now()
    column.is_deleted = True
    column.deleted_at = now
    column.save(update_fields=["is_deleted", "deleted_at"])

    Card.objects.filter(column=column, is_deleted=False).update(is_deleted=True, deleted_at=now)
    return HttpResponse("")


# alias de compatibilidade
column_delete = delete_column


# ======================================================================
# MOVER CARD ENTRE COLUNAS (Drag and Drop)
# ======================================================================

@login_required
@require_POST
@transaction.atomic
def move_card(request):
    data = json.loads(request.body.decode("utf-8"))

    card_id = int(data.get("card_id"))
    new_column_id = int(data.get("new_column_id"))
    new_position = int(data.get("new_position"))

    card = get_object_or_404(Card, id=card_id)
    old_column = card.column
    new_column = get_object_or_404(Column, id=new_column_id)

    old_board = old_column.board
    new_board = new_column.board

    def can_move_in_board(board: Board) -> bool:
        if not request.user.is_authenticated:
            return False

        # staff sempre pode
        if request.user.is_staff:
            return True

        memberships_qs = board.memberships.all()
        if memberships_qs.exists():
            # só OWNER/EDITOR pode mover
            return memberships_qs.filter(
                user=request.user,
                role__in=[BoardMembership.Role.OWNER, BoardMembership.Role.EDITOR],
            ).exists()

        # legado sem memberships
        return bool(board.created_by_id == request.user.id)

    # Permissão no board de origem e no board de destino
    if not can_move_in_board(old_board) or not can_move_in_board(new_board):
        return JsonResponse({"error": "Sem permissão para mover card neste quadro."}, status=403)

    actor = _actor_label(request)
    old_pos = card.position

    if old_column.id == new_column.id:
        # reordenação dentro da mesma coluna
        cards = list(old_column.cards.order_by("position"))
        cards.remove(card)
        cards.insert(new_position, card)

        for index, c in enumerate(cards):
            if c.position != index:
                c.position = index
                c.save(update_fields=["position"])

        _log_card(
            card,
            request,
            f"<p><strong>{actor}</strong> reordenou este card dentro da coluna <strong>{escape(old_column.name)}</strong> (de {old_pos} para {new_position}).</p>",
        )
        return JsonResponse({"status": "ok"})

    # move de coluna
    old_cards = list(old_column.cards.exclude(id=card.id).order_by("position"))
    for index, c in enumerate(old_cards):
        if c.position != index:
            c.position = index
            c.save(update_fields=["position"])

    card.column = new_column
    card.save(update_fields=["column"])

    new_cards = list(new_column.cards.order_by("position"))
    new_cards.insert(new_position, card)

    for index, c in enumerate(new_cards):
        if c.position != index:
            c.position = index
            c.save(update_fields=["position"])

    _log_card(
        card,
        request,
        f"<p><strong>{actor}</strong> moveu este card de <strong>{escape(old_column.name)}</strong> para <strong>{escape(new_column.name)}</strong>.</p>",
    )

    return JsonResponse({"status": "ok"})


# ======================================================================
# MOVER CARD (Modal) — options + refresh painel atividade
# ======================================================================

@login_required
@require_http_methods(["GET"])
def card_move_options(request, card_id):
    card = get_object_or_404(Card, id=card_id, is_deleted=False)
    board_current = card.column.board

    def can_move_in_board(board: Board) -> bool:
        if not request.user.is_authenticated:
            return False

        # staff sempre pode
        if request.user.is_staff:
            return True

        memberships_qs = board.memberships.all()
        if memberships_qs.exists():
            # só OWNER/EDITOR pode mover
            return memberships_qs.filter(
                user=request.user,
                role__in=[BoardMembership.Role.OWNER, BoardMembership.Role.EDITOR],
            ).exists()

        # legado sem memberships: só criador
        return bool(board.created_by_id == request.user.id)

    # Permissão no board atual
    if not can_move_in_board(board_current):
        return JsonResponse({"error": "Sem permissão para mover card neste quadro."}, status=403)

    # Boards acessíveis para mover (mesma regra)
    boards = []

    # 1) boards com membership (qualquer role)
    for bm in BoardMembership.objects.filter(
        user=request.user,
        board__is_deleted=False,
    ).select_related("board"):
        boards.append(bm.board)

    # 2) boards “legado” sem memberships (criador/staff)
    legacy_qs = Board.objects.filter(is_deleted=False)
    if not request.user.is_staff:
        legacy_qs = legacy_qs.filter(created_by_id=request.user.id)

    for b in legacy_qs:
        if not b.memberships.exists():
            boards.append(b)

    # dedup por id
    seen = set()
    uniq = []
    for b in boards:
        if b.id in seen:
            continue
        seen.add(b.id)
        uniq.append(b)

    uniq.sort(key=lambda x: (x.created_at or timezone.now()), reverse=True)

    columns_by_board = {}
    for b in uniq:
        cols = b.columns.filter(is_deleted=False).order_by("position")
        columns_by_board[str(b.id)] = [
            {
                "id": c.id,
                "name": c.name,
                "positions_total_plus_one": (c.cards.count() + 1),
            }
            for c in cols
        ]

    payload = {
        "current": {
            "board_id": board_current.id,
            "board_name": board_current.name,
            "column_id": card.column.id,
            "column_name": card.column.name,
            "position": int(card.position) + 1,
        },
        "boards": [{"id": b.id, "name": b.name} for b in uniq],
        "columns_by_board": columns_by_board,
    }
    return JsonResponse(payload)


# ======================================================================
# MODAL DO CARD
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


def card_modal(request, card_id):
    card = get_object_or_404(Card, id=card_id, is_deleted=False)
    return render(request, "boards/partials/card_modal_body.html", _card_modal_context(card))

# ======================================================================
# IMAGEM PRINCIPAL DO BOARD
# ======================================================================

def update_board_image(request, board_id):
    board = get_object_or_404(Board, id=board_id)
    actor = _actor_label(request)

    if request.method == "GET":
        return render(request, "boards/partials/board_image_form.html", {"board": board})

    if request.method == "POST":
        if "image" in request.FILES and request.FILES["image"]:
            board.image = request.FILES["image"]
            board.save(update_fields=["image"])
            _log_board(board, request, f"<p><strong>{actor}</strong> atualizou a imagem principal do quadro.</p>")
            return HttpResponse('<script>location.reload()</script>')

        url = (request.POST.get("image_url") or "").strip()
        if url:
            try:
                r = requests.get(url, timeout=5)
                if r.status_code == 200:
                    filename = url.split("/")[-1] or "board.jpg"
                    board.image.save(filename, ContentFile(r.content))
                    _log_board(board, request, f"<p><strong>{actor}</strong> atualizou a imagem principal do quadro via URL.</p>")
                    return HttpResponse('<script>location.reload()</script>')
            except Exception:
                pass

        return HttpResponse("<div class='text-red-600'>Erro ao carregar imagem.</div>", status=400)


@require_POST
def remove_board_image(request, board_id):
    board = get_object_or_404(Board, id=board_id)
    actor = _actor_label(request)

    if board.image:
        board.image.delete(save=False)
        board.image = None
        board.save(update_fields=["image"])
        _log_board(board, request, f"<p><strong>{actor}</strong> removeu a imagem principal do quadro.</p>")

    return HttpResponse('<script>location.reload()</script>')


# ======================================================================
# SNIPPET DO CARD
# ======================================================================

def card_snippet(request, card_id):
    card = get_object_or_404(Card, id=card_id)
    return render(request, "boards/partials/card_item.html", {"card": card})


# ======================================================================
# REMOVER TAG
# ======================================================================

@require_POST
def remove_tag(request, card_id):
    card = get_object_or_404(Card, id=card_id)
    actor = _actor_label(request)

    tag = request.POST.get("tag", "").strip()
    if not tag:
        return HttpResponse("Tag inválida", status=400)

    old_tags = [t.strip() for t in (card.tags or "").split(",") if t.strip()]
    new_tags = [t for t in old_tags if t != tag]

    if len(old_tags) == len(new_tags):
        return HttpResponse("Tag não encontrada", status=404)

    card.tags = ", ".join(new_tags)
    card.save(update_fields=["tags"])

    _log_card(card, request, f"<p><strong>{actor}</strong> removeu a etiqueta <strong>{escape(tag)}</strong>.</p>")

    modal_html = render(request, "boards/partials/card_modal_body.html", {"card": card}).content.decode("utf-8")
    snippet_html = render(request, "boards/partials/card_item.html", {"card": card}).content.decode("utf-8")

    return JsonResponse({"modal": modal_html, "snippet": snippet_html, "card_id": card.id})


# ======================================================================
# RENOMEAR BOARD / COLUNA
# ======================================================================

@require_POST
def rename_board(request, board_id):
    board = get_object_or_404(Board, id=board_id)
    actor = _actor_label(request)

    old_name = board.name
    name = request.POST.get("name", "").strip()
    if not name:
        return HttpResponse("Nome inválido", status=400)

    board.name = name
    board.save(update_fields=["name"])

    _log_board(
        board,
        request,
        f"<p><strong>{actor}</strong> renomeou o quadro de <strong>{escape(old_name)}</strong> para <strong>{escape(name)}</strong>.</p>",
    )

    return HttpResponse("OK", status=200)


@require_POST
def rename_column(request, column_id):
    column = get_object_or_404(Column, id=column_id)
    actor = _actor_label(request)

    old_name = column.name
    name = request.POST.get("name", "").strip()
    if not name:
        return HttpResponse("Nome inválido", status=400)

    column.name = name
    column.save(update_fields=["name"])

    # loga nos cards da coluna (excesso controlado)
    for c in Card.objects.filter(column=column, is_deleted=False):
        _log_card(
            c,
            request,
            f"<p><strong>{actor}</strong> renomeou a coluna de <strong>{escape(old_name)}</strong> para <strong>{escape(name)}</strong>.</p>",
        )

    _log_board(
        column.board,
        request,
        f"<p><strong>{actor}</strong> renomeou a coluna de <strong>{escape(old_name)}</strong> para <strong>{escape(name)}</strong>.</p>",
    )

    return render(request, "boards/partials/column_item.html", {"column": column})


# ======================================================================
# WALLPAPER DO BOARD + CSS
# ======================================================================

def _default_wallpaper_url():
    """
    Default resiliente:
    - Preferir /static/images/<DEFAULT_WALLPAPER_FILENAME>
    - Se não existir em staticfiles, tentar /media/home_wallpapers/<DEFAULT_WALLPAPER_FILENAME>
    - Fallback final: /static/images/<DEFAULT_WALLPAPER_FILENAME>
    """
    from django.templatetags.static import static as static_url

    rel_static = f"images/{DEFAULT_WALLPAPER_FILENAME}"

    # 1) tenta achar em STATICFILES (quando collectstatic está ok)
    try:
        from django.contrib.staticfiles import finders
        found = finders.find(rel_static)
        if found:
            return static_url(rel_static)
    except Exception:
        pass

    # 2) tenta achar em MEDIA (caso alguém tenha colocado o default lá)
    try:
        rel_media = f"home_wallpapers/{DEFAULT_WALLPAPER_FILENAME}"
        if default_storage.exists(rel_media):
            return default_storage.url(rel_media)
    except Exception:
        pass

    # 3) fallback final
    return static_url(rel_static)


def update_board_wallpaper(request, board_id):
    board = get_object_or_404(Board, id=board_id)
    actor = _actor_label(request)

    if request.method == "GET":
        return render(request, "boards/partials/wallpaper_form.html", {"board": board})

    if request.method == "POST":
        if "image" in request.FILES and request.FILES["image"]:
            board.background_image = request.FILES["image"]
            board.background_url = ""
            board.save(update_fields=["background_image", "background_url"])
            _log_board(board, request, f"<p><strong>{actor}</strong> atualizou o wallpaper do quadro (upload).</p>")
            return HttpResponse('<script>location.reload()</script>')

        url = (request.POST.get("image_url") or "").strip()
        if url:
            board.background_url = url
            board.background_image = None
            board.save(update_fields=["background_image", "background_url"])
            _log_board(board, request, f"<p><strong>{actor}</strong> atualizou o wallpaper do quadro (URL).</p>")
            return HttpResponse('<script>location.reload()</script>')

        return HttpResponse("Erro", status=400)


def board_wallpaper_css(request, board_id):
    board = get_object_or_404(Board, id=board_id, is_deleted=False)

    if getattr(board, "background_image", None):
        img_url = board.background_image.url
    elif (getattr(board, "background_url", "") or "").strip():
        img_url = escape((getattr(board, "background_url", "") or "").strip())
    else:
        img_url = _default_wallpaper_url()

    css = f"""
    body {{
        background-image: url('{img_url}') !important;
        background-size: cover !important;
        background-position: center !important;
        background-attachment: fixed !important;
        background-repeat: no-repeat !important;
        background-color: transparent !important;
    }}
    """
    resp = HttpResponse(css, content_type="text/css")
    resp["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp["Pragma"] = "no-cache"
    resp["Expires"] = "0"
    return resp


@require_POST
def remove_board_wallpaper(request, board_id):
    board = get_object_or_404(Board, id=board_id)
    actor = _actor_label(request)

    if board.background_image:
        board.background_image.delete(save=False)
        board.background_image = None

    board.background_url = ""
    board.save(update_fields=["background_image", "background_url"])

    _log_board(board, request, f"<p><strong>{actor}</strong> removeu o wallpaper do quadro.</p>")
    return HttpResponse('<script>location.reload()</script>')


# ======================================================================
# HOME WALLPAPER (Organization.home_wallpaper_filename)
# ======================================================================

def home_wallpaper_css(request):
    # default do sistema (robusto)
    url = _default_wallpaper_url()

    if request.user.is_authenticated:
        org = get_or_create_user_default_organization(request.user)
        filename = (getattr(org, "home_wallpaper_filename", "") or "").strip()

        # Se for vazio OU for o default, mantém /static (não força /media)
        if filename and filename != DEFAULT_WALLPAPER_FILENAME:
            rel = f"home_wallpapers/{filename}"
            try:
                if default_storage.exists(rel):
                    url = default_storage.url(rel)
            except Exception:
                pass

    css = f"""
    body {{
        background-image: url('{url}') !important;
        background-size: cover !important;
        background-position: center !important;
        background-attachment: fixed !important;
        background-repeat: no-repeat !important;
        background-color: transparent !important;
    }}
    """
    resp = HttpResponse(css, content_type="text/css")
    resp["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp["Pragma"] = "no-cache"
    resp["Expires"] = "0"
    return resp


# ======================================================================
# HOME WALLPAPER (upload/remoção)
# ======================================================================

def update_home_wallpaper(request):
    if request.method == "GET":
        return render(request, "boards/partials/home_wallpaper_form.html", {})

    if not request.user.is_authenticated:
        return HttpResponse("Login necessário.", status=401)

    org = get_or_create_user_default_organization(request.user)
    if not org:
        return HttpResponse("Organização não encontrada.", status=400)

    actor = _actor_label(request)

    def _anchor_board_for_org(_org):
        try:
            return Board.objects.filter(organization=_org, is_deleted=False).order_by("-id").first()
        except Exception:
            return None

    # UPLOAD
    if "image" in request.FILES and request.FILES["image"]:
        file = request.FILES["image"]
        ext = os.path.splitext(file.name or "")[1] or ".jpg"
        filename = f"{uuid.uuid4().hex}{ext}"
        rel = f"home_wallpapers/{filename}"

        # salva via storage (mesma “fonte de verdade” do CSS)
        default_storage.save(rel, file)

        # remove o antigo (não remove o default do sistema)
        old = (getattr(org, "home_wallpaper_filename", "") or "").strip()
        if old and old != DEFAULT_WALLPAPER_FILENAME:
            old_rel = f"home_wallpapers/{old}"
            try:
                if default_storage.exists(old_rel):
                    default_storage.delete(old_rel)
            except Exception:
                pass

        org.home_wallpaper_filename = filename
        org.save(update_fields=["home_wallpaper_filename"])

        board_anchor = _anchor_board_for_org(org)
        if board_anchor:
            _log_board(board_anchor, request, f"<p><strong>{actor}</strong> atualizou o wallpaper da HOME (upload).</p>")

        return HttpResponse('<script>location.reload()</script>')

    # IMPORTAR VIA URL
    url = (request.POST.get("image_url") or "").strip()
    if url:
        try:
            r = requests.get(url, timeout=8)
            if r.status_code == 200 and r.content:
                parsed_ext = os.path.splitext((url.split("?")[0] or "").strip())[1] or ".jpg"
                filename = f"{uuid.uuid4().hex}{parsed_ext}"
                rel = f"home_wallpapers/{filename}"

                default_storage.save(rel, ContentFile(r.content))

                old = (getattr(org, "home_wallpaper_filename", "") or "").strip()
                if old and old != DEFAULT_WALLPAPER_FILENAME:
                    old_rel = f"home_wallpapers/{old}"
                    try:
                        if default_storage.exists(old_rel):
                            default_storage.delete(old_rel)
                    except Exception:
                        pass

                org.home_wallpaper_filename = filename
                org.save(update_fields=["home_wallpaper_filename"])

                board_anchor = _anchor_board_for_org(org)
                if board_anchor:
                    _log_board(board_anchor, request, f"<p><strong>{actor}</strong> atualizou o wallpaper da HOME (URL).</p>")

                return HttpResponse('<script>location.reload()</script>')
        except Exception:
            pass

    return HttpResponse("Erro ao importar imagem", status=400)


@require_POST
def remove_home_wallpaper(request):
    if not request.user.is_authenticated:
        return HttpResponse("Login necessário.", status=401)

    org = get_or_create_user_default_organization(request.user)
    if not org:
        return HttpResponse("Organização não encontrada.", status=400)

    actor = _actor_label(request)

    filename = (getattr(org, "home_wallpaper_filename", "") or "").strip()

    # apaga somente se não for o default do sistema
    if filename and filename != DEFAULT_WALLPAPER_FILENAME:
        rel = f"home_wallpapers/{filename}"
        try:
            if default_storage.exists(rel):
                default_storage.delete(rel)
        except Exception:
            pass

    # volta para o default do sistema
    org.home_wallpaper_filename = DEFAULT_WALLPAPER_FILENAME
    org.save(update_fields=["home_wallpaper_filename"])

    # auditoria best-effort
    try:
        board_anchor = Board.objects.filter(organization=org, is_deleted=False).order_by("-id").first()
        if board_anchor:
            _log_board(board_anchor, request, f"<p><strong>{actor}</strong> removeu o wallpaper da HOME.</p>")
    except Exception:
        pass

    return HttpResponse('<script>location.reload()</script>')


# ======================================================================
# ATIVIDADE NO CARD (Quill) + upload
# ======================================================================

@login_required
@require_http_methods(["GET"])
def activity_panel(request, card_id):
    card = get_object_or_404(Card, id=card_id, is_deleted=False)

    board = card.column.board
    memberships_qs = board.memberships.all()

    # regra de acesso igual ao board_detail: se tem membership, exige membership
    if memberships_qs.exists():
        if not memberships_qs.filter(user=request.user).exists():
            return HttpResponse("Você não tem acesso a este quadro.", status=403)

    return render(request, "boards/partials/card_activity_panel.html", {"card": card})


@require_POST
def add_activity(request, card_id):
    card = get_object_or_404(Card, id=card_id)
    actor = _actor_label(request)

    raw = request.POST.get("content", "").strip()
    if not raw:
        return HttpResponse("Conteúdo vazio", status=400)

    html = raw

    _log_card(
        card,
        request,
        f"<p><strong>{actor}</strong> adicionou uma atividade:</p>{html}",
        attachment=None,
    )

    img_urls = re.findall(r'src="([^"]+)"', html)
    for url in img_urls:
        if "/media/quill/" not in url:
            continue

        relative_path = url.split("/media/")[-1]
        if card.attachments.filter(file=relative_path).exists():
            continue

        CardAttachment.objects.create(card=card, file=relative_path)

    rendered = render(
        request,
        "boards/partials/card_activity_panel.html",
        {"card": card},
    ).content.decode("utf-8")

    return HttpResponse(rendered)


@csrf_exempt
def quill_upload(request):
    if request.method != "POST" or "image" not in request.FILES:
        return JsonResponse({"error": "Invalid request"}, status=400)

    img = request.FILES["image"]
    ext = os.path.splitext(img.name or "")[1] or ".png"
    filename = f"{uuid.uuid4().hex}{ext}"

    file_path = default_storage.save(f"quill/{filename}", ContentFile(img.read()))
    file_url = default_storage.url(file_path)
    return JsonResponse({"success": 1, "url": file_url})


@require_POST
def add_attachment(request, card_id):
    card = get_object_or_404(Card, id=card_id)
    actor = _actor_label(request)

    if "file" not in request.FILES:
        return HttpResponse("Nenhum arquivo enviado", status=400)

    uploaded = request.FILES["file"]
    desc = (request.POST.get("description") or "").strip()

    attachment = CardAttachment.objects.create(
        card=card,
        file=uploaded,
        description=desc,
    )

    # auditoria
    pretty_name = attachment.file.name.split("/")[-1]
    if desc:
        _log_card(
            card,
            request,
            f"<p><strong>{actor}</strong> adicionou um anexo: <strong>{escape(pretty_name)}</strong> — {escape(desc)}.</p>",
            attachment=attachment.file,
        )
    else:
        _log_card(
            card,
            request,
            f"<p><strong>{actor}</strong> adicionou um anexo: <strong>{escape(pretty_name)}</strong>.</p>",
            attachment=attachment.file,
        )

    return render(request, "boards/partials/attachment_item.html", {"attachment": attachment})



# ======================================================================
# COMPARTILHAR BOARD
# ======================================================================

@require_http_methods(["GET", "POST"])
def board_share(request, board_id):
    if not request.user.is_authenticated:
        return HttpResponse("Login necessário.", status=401)

    board = get_object_or_404(Board, id=board_id, is_deleted=False)

    memberships_qs = board.memberships.select_related("user")
    if memberships_qs.exists():
        if not memberships_qs.filter(user=request.user, role=BoardMembership.Role.OWNER).exists():
            return HttpResponse("Você não tem permissão para compartilhar este quadro.", status=403)
    else:
        if board.created_by_id != request.user.id and not request.user.is_staff:
            return HttpResponse("Você não tem permissão para compartilhar este quadro.", status=403)

    memberships = board.memberships.select_related("user").order_by("role", "user__username")

    if request.method == "GET":
        return render(request, "boards/partials/board_share_form.html", {"board": board, "memberships": memberships})

    actor = _actor_label(request)

    identifier = (request.POST.get("identifier") or "").strip()
    role = (request.POST.get("role") or BoardMembership.Role.VIEWER).strip().lower()

    if role not in {
        BoardMembership.Role.OWNER,
        BoardMembership.Role.EDITOR,
        BoardMembership.Role.VIEWER,
    }:
        role = BoardMembership.Role.VIEWER

    if not identifier:
        return render(
            request,
            "boards/partials/board_share_form.html",
            {"board": board, "memberships": memberships, "msg_error": "Informe e-mail ou username."},
            status=400,
        )

    User = get_user_model()
    target = User.objects.filter(Q(username__iexact=identifier) | Q(email__iexact=identifier)).first()

    if not target:
        return render(
            request,
            "boards/partials/board_share_form.html",
            {"board": board, "memberships": memberships, "msg_error": "Usuário não encontrado."},
            status=404,
        )

    if target.id == request.user.id:
        return render(
            request,
            "boards/partials/board_share_form.html",
            {"board": board, "memberships": memberships, "msg_error": "Você já é membro deste quadro."},
            status=400,
        )

    obj, created = BoardMembership.objects.get_or_create(
        board=board,
        user=target,
        defaults={"role": role},
    )

    if not created and obj.role != role:
        obj.role = role
        obj.save(update_fields=["role"])

    # AUDITORIA
    _log_board(
        board,
        request,
        f"<p><strong>{actor}</strong> compartilhou o quadro com <strong>{escape(target.email or target.get_username())}</strong> como <strong>{escape(role)}</strong>.</p>",
    )

    memberships = board.memberships.select_related("user").order_by("role", "user__username")

    return render(
        request,
        "boards/partials/board_share_form.html",
        {
            "board": board,
            "memberships": memberships,
            "msg_success": f"Compartilhado com {escape(target.get_username())} ({escape(target.email or '-')}).",
        },
        status=200,
    )


@require_POST
def board_share_remove(request, board_id, user_id):
    if not request.user.is_authenticated:
        return HttpResponse("Login necessário.", status=401)

    board = get_object_or_404(Board, id=board_id, is_deleted=False)

    memberships_qs = board.memberships.select_related("user")
    if memberships_qs.exists():
        if not memberships_qs.filter(user=request.user, role=BoardMembership.Role.OWNER).exists():
            return HttpResponse("Você não tem permissão para remover acessos deste quadro.", status=403)
    else:
        if board.created_by_id != request.user.id and not request.user.is_staff:
            return HttpResponse("Você não tem permissão para remover acessos deste quadro.", status=403)

    actor = _actor_label(request)

    membership = BoardMembership.objects.filter(board=board, user_id=user_id).select_related("user").first()
    memberships = board.memberships.select_related("user").order_by("role", "user__username")

    if not membership:
        return render(
            request,
            "boards/partials/board_share_form.html",
            {"board": board, "memberships": memberships, "msg_error": "Acesso não encontrado."},
            status=404,
        )

    if membership.role == BoardMembership.Role.OWNER:
        owners_count = board.memberships.filter(role=BoardMembership.Role.OWNER).count()
        if owners_count <= 1:
            return render(
                request,
                "boards/partials/board_share_form.html",
                {"board": board, "memberships": memberships, "msg_error": "Não é possível remover o último DONO do quadro."},
                status=400,
            )

    removed_user = membership.user
    membership.delete()

    _log_board(
        board,
        request,
        f"<p><strong>{actor}</strong> removeu o acesso de <strong>{escape(removed_user.email or removed_user.get_username())}</strong> do quadro.</p>",
    )

    memberships = board.memberships.select_related("user").order_by("role", "user__username")

    return render(
        request,
        "boards/partials/board_share_form.html",
        {"board": board, "memberships": memberships, "msg_success": f"Acesso removido: {escape(removed_user.get_username())}."},
        status=200,
    )


# ======================================================================
# USERS
# ======================================================================

@staff_member_required
def create_user(request):
    if request.method == "POST":
        form = UserCreationForm(request.POST)
        email = (request.POST.get("email") or "").strip()

        if form.is_valid():
            user = form.save(commit=False)
            if email:
                user.email = email
            user.save()
            return redirect("boards:boards_index")
    else:
        form = UserCreationForm()

    return render(request, "boards/create_user.html", {"form": form})




# ======================================================================
# CHECKLISTS
# ======================================================================

# ======================================================================
# CHECKLISTS — PERMISSÕES (padrão do board)
# ======================================================================

def _can_view_board(request, board: Board) -> bool:
    if not request.user.is_authenticated:
        return False
    if request.user.is_staff:
        return True

    memberships_qs = board.memberships.all()
    if memberships_qs.exists():
        return memberships_qs.filter(user=request.user).exists()

    # legado sem memberships
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

    # legado sem memberships
    return bool(board.created_by_id == request.user.id)


# ======================================================================
# CHECKLISTS — REORDER (Drag and Drop) + AUDITORIA
# ======================================================================

@login_required
@require_POST
def checklists_reorder(request, card_id):
    card = get_object_or_404(Card, id=card_id, is_deleted=False)
    board = card.column.board

    if not _can_edit_board(request, board):
        return JsonResponse({"ok": False, "error": "Sem permissão."}, status=403)

    try:
        payload = json.loads(request.body.decode("utf-8"))
        order = payload.get("order", [])
        if not isinstance(order, list) or not order:
            return JsonResponse({"ok": False, "error": "order inválido"}, status=400)
        order = [int(x) for x in order]
    except Exception:
        return JsonResponse({"ok": False, "error": "JSON inválido"}, status=400)

    valid_ids = set(Checklist.objects.filter(card=card).values_list("id", flat=True))
    if set(order) != valid_ids:
        return JsonResponse({"ok": False, "error": "Checklist fora do card."}, status=400)

    with transaction.atomic():
        for idx, cid in enumerate(order):
            Checklist.objects.filter(id=cid, card=card).update(position=idx)

    actor = _actor_label(request)
    _log_card(card, request, f"<p><strong>{actor}</strong> reordenou checklists (drag).</p>")

    return JsonResponse({"ok": True})


@login_required
@require_POST
def checklist_items_reorder(request, card_id):
    card = get_object_or_404(Card, id=card_id, is_deleted=False)
    board = card.column.board

    if not _can_edit_board(request, board):
        return JsonResponse({"ok": False, "error": "Sem permissão."}, status=403)

    try:
        payload = json.loads(request.body.decode("utf-8"))
        updates = payload.get("updates", [])
        if not isinstance(updates, list) or not updates:
            return JsonResponse({"ok": False, "error": "updates inválido"}, status=400)
    except Exception:
        return JsonResponse({"ok": False, "error": "JSON inválido"}, status=400)

    checklist_ids = set()
    item_ids = set()

    # valida tipos + coleta ids
    for u in updates:
        try:
            checklist_ids.add(int(u.get("checklist_id")))
            item_ids.add(int(u.get("item_id")))
            int(u.get("position"))
        except Exception:
            return JsonResponse({"ok": False, "error": "Payload inválido (tipos)."}, status=400)

    # valida checklists pertencem ao card
    valid_checklists = set(
        Checklist.objects.filter(card=card, id__in=checklist_ids).values_list("id", flat=True)
    )
    if checklist_ids - valid_checklists:
        return JsonResponse({"ok": False, "error": "Checklist fora do card."}, status=400)

    # valida itens pertencem ao card
    items = list(ChecklistItem.objects.filter(card=card, id__in=item_ids))
    items_map = {it.id: it for it in items}
    if set(item_ids) - set(items_map.keys()):
        return JsonResponse({"ok": False, "error": "Item fora do card."}, status=400)

    changed = []
    for u in updates:
        iid = int(u["item_id"])
        cid = int(u["checklist_id"])
        pos = int(u["position"])
        it = items_map[iid]

        if it.checklist_id != cid or it.position != pos:
            it.checklist_id = cid
            it.position = pos
            changed.append(it)

    with transaction.atomic():
        if changed:
            ChecklistItem.objects.bulk_update(changed, ["checklist_id", "position"])

    actor = _actor_label(request)
    _log_card(card, request, f"<p><strong>{actor}</strong> reordenou itens de checklist (drag).</p>")

    return JsonResponse({"ok": True})


# ======================================================================
# CHECKLISTS — CRUD + AUDITORIA
# ======================================================================

@login_required
@require_POST
def checklist_add(request, card_id):
    card = get_object_or_404(Card, id=card_id, is_deleted=False)
    board = card.column.board
    if not _can_edit_board(request, board):
        return HttpResponse("Sem permissão.", status=403)

    actor = _actor_label(request)
    title = (request.POST.get("title") or "").strip() or "Checklist"
    position = card.checklists.count()

    checklist = Checklist.objects.create(card=card, title=title, position=position)

    _log_card(card, request, f"<p><strong>{actor}</strong> criou a checklist <strong>{escape(checklist.title)}</strong>.</p>")
    return render(request, "boards/partials/checklist_list.html", {"card": card})


@login_required
@require_POST
def checklist_rename(request, checklist_id):
    checklist = get_object_or_404(Checklist, id=checklist_id)
    card = checklist.card
    board = card.column.board
    if not _can_edit_board(request, board):
        return HttpResponse("Sem permissão.", status=403)

    actor = _actor_label(request)
    old_title = checklist.title
    title = (request.POST.get("title") or "").strip()
    if not title:
        return HttpResponse("Título inválido.", status=400)

    checklist.title = title
    checklist.save(update_fields=["title"])

    _log_card(card, request, f"<p><strong>{actor}</strong> renomeou a checklist de <strong>{escape(old_title)}</strong> para <strong>{escape(title)}</strong>.</p>")
    return render(request, "boards/partials/checklist_list.html", {"card": card})


@login_required
@require_POST
def checklist_delete(request, checklist_id):
    checklist = get_object_or_404(Checklist, id=checklist_id)
    card = checklist.card
    board = card.column.board
    if not _can_edit_board(request, board):
        return HttpResponse("Sem permissão.", status=403)

    actor = _actor_label(request)
    title = checklist.title
    checklist.delete()

    # reindex positions
    for idx, c in enumerate(card.checklists.order_by("position", "created_at")):
        if c.position != idx:
            c.position = idx
            c.save(update_fields=["position"])

    _log_card(card, request, f"<p><strong>{actor}</strong> excluiu a checklist <strong>{escape(title)}</strong>.</p>")
    return render(request, "boards/partials/checklist_list.html", {"card": card})


@login_required
@require_POST
def checklist_add_item(request, checklist_id):
    checklist = get_object_or_404(Checklist, id=checklist_id)
    card = checklist.card
    board = card.column.board
    if not _can_edit_board(request, board):
        return HttpResponse("Sem permissão.", status=403)

    actor = _actor_label(request)
    text = (request.POST.get("text") or "").strip()
    if not text:
        return HttpResponse("Texto vazio", status=400)

    position = checklist.items.count()
    item = ChecklistItem.objects.create(card=card, checklist=checklist, text=text, position=position)

    _log_card(card, request, f"<p><strong>{actor}</strong> adicionou item na checklist <strong>{escape(checklist.title)}</strong>: {escape(item.text)}.</p>")
    return render(request, "boards/partials/checklist_list.html", {"card": card})


@login_required
@require_POST
def checklist_toggle_item(request, item_id):
    item = get_object_or_404(ChecklistItem, id=item_id)
    card = item.card
    board = card.column.board
    if not _can_edit_board(request, board):
        return HttpResponse("Sem permissão.", status=403)

    actor = _actor_label(request)

    item.is_done = not item.is_done
    item.save(update_fields=["is_done"])

    status = "concluiu" if item.is_done else "reabriu"
    _log_card(card, request, f"<p><strong>{actor}</strong> {status} um item da checklist: {escape(item.text)}.</p>")

    return render(request, "boards/partials/checklist_item.html", {"item": item})


@login_required
@require_http_methods(["POST"])
def checklist_delete_item(request, item_id):
    item = get_object_or_404(ChecklistItem, id=item_id)
    card = item.card
    board = card.column.board
    if not _can_edit_board(request, board):
        return HttpResponse("Sem permissão.", status=403)

    actor = _actor_label(request)
    text = item.text
    checklist = item.checklist
    item.delete()

    # reindex positions
    if checklist:
        for idx, it in enumerate(checklist.items.order_by("position", "created_at")):
            if it.position != idx:
                it.position = idx
                it.save(update_fields=["position"])

    _log_card(card, request, f"<p><strong>{actor}</strong> excluiu um item da checklist: {escape(text)}.</p>")
    return render(request, "boards/partials/checklist_list.html", {"card": card})


@login_required
@require_POST
def checklist_update_item(request, item_id):
    item = get_object_or_404(ChecklistItem, id=item_id)
    card = item.card
    board = card.column.board
    if not _can_edit_board(request, board):
        return HttpResponse("Sem permissão.", status=403)

    actor = _actor_label(request)
    old = item.text
    text = (request.POST.get("text") or "").strip()
    if not text:
        return HttpResponse("Texto vazio", status=400)

    item.text = text
    item.save(update_fields=["text"])

    _log_card(card, request, f"<p><strong>{actor}</strong> editou um item da checklist de {escape(old)} para {escape(text)}.</p>")
    return render(request, "boards/partials/checklist_item.html", {"item": item})




# ======================================================================
# CHECKLISTS — COMPAT/LEGADO (para não quebrar rotas antigas)
# ======================================================================

@login_required
@require_POST
def checklist_move(request, checklist_id):
    checklist = get_object_or_404(Checklist, id=checklist_id)
    card = checklist.card
    board = card.column.board

    if not _can_edit_board(request, board):
        return HttpResponse("Sem permissão.", status=403)

    direction = (request.POST.get("direction") or "").strip().lower()
    new_position_raw = (request.POST.get("position") or request.POST.get("new_position") or "").strip()

    checklists = list(card.checklists.order_by("position", "created_at"))
    if not checklists:
        return render(request, "boards/partials/checklist_list.html", {"card": card})

    try:
        current_index = next(i for i, c in enumerate(checklists) if c.id == checklist.id)
    except StopIteration:
        return HttpResponseBadRequest("Checklist inválido.")

    # Determina novo índice
    if new_position_raw:
        try:
            # aceita 0-based e 1-based (se vier 1..N)
            pos = int(new_position_raw)
            if 1 <= pos <= len(checklists):
                new_index = pos - 1
            else:
                new_index = pos
        except Exception:
            return HttpResponseBadRequest("position inválido.")
    elif direction in ("up", "down"):
        new_index = current_index - 1 if direction == "up" else current_index + 1
    else:
        return HttpResponseBadRequest("Informe 'direction' (up/down) ou 'position'.")

    new_index = max(0, min(len(checklists) - 1, new_index))
    if new_index != current_index:
        moved = checklists.pop(current_index)
        checklists.insert(new_index, moved)

        with transaction.atomic():
            for idx, c in enumerate(checklists):
                if c.position != idx:
                    c.position = idx
                    c.save(update_fields=["position"])

        actor = _actor_label(request)
        _log_card(card, request, f"<p><strong>{actor}</strong> reordenou checklists (legado).</p>")

    return render(request, "boards/partials/checklist_list.html", {"card": card})


@login_required
@require_POST
def checklist_move_up(request, item_id):
    return _checklist_move_item_delta(request, item_id, delta=-1)


@login_required
@require_POST
def checklist_move_down(request, item_id):
    return _checklist_move_item_delta(request, item_id, delta=+1)


def _checklist_move_item_delta(request, item_id, delta: int):
    item = get_object_or_404(ChecklistItem, id=item_id)
    card = item.card
    board = card.column.board

    if not _can_edit_board(request, board):
        return HttpResponse("Sem permissão.", status=403)

    if not item.checklist_id:
        return HttpResponseBadRequest("Item não está associado a um checklist.")

    items = list(
        ChecklistItem.objects.filter(checklist_id=item.checklist_id).order_by("position", "created_at")
    )

    try:
        idx = next(i for i, it in enumerate(items) if it.id == item.id)
    except StopIteration:
        return HttpResponseBadRequest("Item inválido.")

    new_idx = idx + delta
    if new_idx < 0 or new_idx >= len(items):
        return render(request, "boards/partials/checklist_list.html", {"card": card})

    a = items[idx]
    b = items[new_idx]

    with transaction.atomic():
        a_pos = a.position
        b_pos = b.position
        a.position = b_pos
        b.position = a_pos
        a.save(update_fields=["position"])
        b.save(update_fields=["position"])

    actor = _actor_label(request)
    _log_card(card, request, f"<p><strong>{actor}</strong> reordenou item de checklist (legado).</p>")

    return render(request, "boards/partials/checklist_list.html", {"card": card})
