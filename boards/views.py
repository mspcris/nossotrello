# ======================================================================
# IMPORTAÇÕES
# ======================================================================

import os
import json
import base64
import re
import uuid
import requests

from django.conf import settings
from django.shortcuts import render, get_object_or_404, redirect
from django.http import HttpResponse, JsonResponse, HttpResponseBadRequest
from django.views.decorators.http import require_POST, require_http_methods
from django.db import transaction
from django.utils import timezone
from django.utils.html import escape
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.views.decorators.csrf import csrf_exempt
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth import get_user_model
from django.db.models import Q
from urllib.parse import parse_qs


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
# HELPER – Organização "default" por usuário
# ======================================================================


def get_or_create_user_default_organization(user):
    """
    Garante que cada usuário tenha uma organização "dona" dos boards.
    - Se não existir, cria.
    - Garante também o membership como OWNER.
    """
    if not user.is_authenticated:
        return None

    display_name = user.get_full_name() or user.get_username() or str(user)

    org, _created = Organization.objects.get_or_create(
        owner=user,
        defaults={"name": f"Workspace de {display_name}"},
    )

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

        owned_ids = qs.filter(role=BoardMembership.Role.OWNER).values_list("board_id", flat=True)
        shared_ids = qs.exclude(role=BoardMembership.Role.OWNER).values_list("board_id", flat=True)

        owned_boards = Board.objects.filter(id__in=owned_ids, is_deleted=False).distinct().order_by("-created_at")
        shared_boards = Board.objects.filter(id__in=shared_ids, is_deleted=False).distinct().order_by("-created_at")
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
    if memberships_qs.exists():
        if not request.user.is_authenticated:
            return HttpResponse("Você não tem acesso a este quadro.", status=403)
        if not memberships_qs.filter(user=request.user).exists():
            return HttpResponse("Você não tem acesso a este quadro.", status=403)

    columns = board.columns.filter(is_deleted=False).order_by("position")
    return render(request, "boards/board_detail.html", {"board": board, "columns": columns})


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

    column.theme = theme
    column.save(update_fields=["theme"])
    return render(request, "boards/partials/column_item.html", {"column": column})


# ======================================================================
# REORDENAR COLUNAS
# ======================================================================

import json
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404

from .models import Board, Column


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

         # descrição (HTML do Quill) — pode vir fora do form
        raw_desc = (request.POST.get("description") or card.description or "")

        # garante variáveis sempre definidas
        clean_desc, extracted_file = extract_base64_and_convert(raw_desc)

        # se não veio base64, tenta pegar a primeira <img src="/media/...">
        # (ex: /media/quill/..., /media/attachments/...)
        if not extracted_file:
            m = re.search(r'<img[^>]+src="([^"]+)"', raw_desc or "")
            if m:
                url = (m.group(1) or "").strip()
                if "/media/" in url:
                    relative_path = url.split("/media/")[-1].strip()
                    if relative_path:
                        _set_cover_from_relative_path(card, relative_path)

        # regra: descrição não guarda base64 (pesado). Mantém <img src="/media/..."> se existir
        card.description = strip_img_tags(clean_desc)

        # capa via base64 (se model suportar)
        _set_cover_from_file(card, extracted_file)



        # 2) se não veio base64, tenta pegar a primeira <img src="/media/...">
        # (ex: /media/quill/..., /media/attachments/...)
        if not extracted_file:
            m = re.search(r'<img[^>]+src="([^"]+)"', raw_desc or "")
            if m:
                url = (m.group(1) or "").strip()
                if "/media/" in url:
                    relative_path = url.split("/media/")[-1].strip()
                    if relative_path:
                        _set_cover_from_relative_path(card, relative_path)

        # 3) regra: descrição não guarda <img>
        card.description = strip_img_tags(clean_desc)

        # capa via base64 (se model suportar)
        _set_cover_from_file(card, extracted_file)

        card.column = column
        card.position = column.cards.count()
        card.save()

        # log se capa existir e estiver definida
        if _card_has_cover_image(card) and getattr(card, "cover_image", None):
            if card.cover_image:
                CardLog.objects.create(
                    card=card,
                    content="<p><strong>Capa definida na criação do card</strong></p>",
                )

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

            CardLog.objects.create(
                card=card,
                content=card.description or "",
            )

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

    old_title = card.title
    old_desc = card.description or ""

    # título
    card.title = request.POST.get("title", card.title)

    # descrição (HTML do Quill)
    raw_desc = request.POST.get("description", card.description or "")

    # 1) extrai base64 primeiro (se houver)
    clean_desc, extracted_file = extract_base64_and_convert(raw_desc)
    # 2) regra: descrição nunca guarda <img>
    clean_desc = strip_img_tags(clean_desc)
    card.description = clean_desc

    # capa via base64 (se model suportar)
    _set_cover_from_file(card, extracted_file)

    # tags
    old_tags_raw = card.tags or ""
    new_tags_raw = request.POST.get("tags", old_tags_raw) or ""

    old_tags = [t.strip() for t in old_tags_raw.split(",") if t.strip()]
    new_tags = [t.strip() for t in new_tags_raw.split(",") if t.strip()]

    card.tags = new_tags_raw
    removed = [t for t in old_tags if t not in new_tags]
    added = [t for t in new_tags if t not in old_tags]

    card.save()

    # logs de tags
    for t in removed:
        CardLog.objects.create(card=card, content=f"Etiqueta removida: {t}")
    for t in added:
        CardLog.objects.create(card=card, content=f"Etiqueta adicionada: {t}")

    # log de descrição
    if (old_desc or "").strip() != (card.description or "").strip():
        CardLog.objects.create(
            card=card,
            content=("<p><strong>Descrição atualizada</strong></p>" f"{card.description}"),
        )

    # log de título
    if (old_title or "").strip() != (card.title or "").strip():
        CardLog.objects.create(
            card=card,
            content=f"<p><strong>Título atualizado</strong></p><p>{escape(card.title)}</p>",
        )

    # fallback
    if (
        not removed
        and not added
        and (old_desc.strip() == (card.description or "").strip())
        and (old_title.strip() == card.title.strip())
    ):
        CardLog.objects.create(card=card, content="Card atualizado.")

    return render(request, "boards/partials/card_modal_body.html", {"card": card})


# ======================================================================
# ATUALIZAR CARD_COVER (colar URL /media/)
# ======================================================================

@require_POST
def set_card_cover(request, card_id):
    card = get_object_or_404(Card, id=card_id)

    # Diagnóstico rápido (depois a gente remove)
    print("COVER/SET content_type:", request.content_type)
    print("COVER/SET POST keys:", list(request.POST.keys()))
    #print("COVER/SET body head:", (request.body or b"")[:200])

    # 1) tenta via POST normal (form-data / x-www-form-urlencoded)
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

    # 3) tenta body “cru” (alguns fetch mandam só a string)
    if not url and request.body:
        raw = request.body.decode("utf-8", errors="ignore").strip()

        # ex: "/media/quill/xxx.png"
        if raw.startswith("/media/") or raw.startswith("http"):
            url = raw
        else:
            # ex: "url=/media/quill/xxx.png"
            parsed = parse_qs(raw)
            for k in ("url", "src", "image_url", "cover_url", "path", "file_url"):
                if k in parsed and parsed[k]:
                    url = (parsed[k][0] or "").strip()
                    if url:
                        break

    if not url:
        return HttpResponse("URL inválida", status=400)

    # aceita "/media/..." ou url absoluta com "/media/"
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
    CardLog.objects.create(
        card=card,
        content=(
            "<p><strong>Imagem colada na descrição</strong> (definida como capa)</p>"
            f'<p><img src="{escape(file_url)}" /></p>'
        ),
    )

    return render(request, "boards/partials/card_modal_body.html", {"card": card})



@require_POST
def remove_card_cover(request, card_id):
    card = get_object_or_404(Card, id=card_id)

    if not _card_has_cover_image(card):
        return HttpResponse("cover_image não configurado no model Card.", status=400)

    if card.cover_image:
        card.cover_image = None
        card.save(update_fields=["cover_image"])

        CardLog.objects.create(card=card, content="<p><strong>Capa removida</strong></p>")

    return render(request, "boards/partials/card_modal_body.html", {"card": card})


# ======================================================================
# DELETAR CARD (soft delete)
# ======================================================================


@require_POST
def delete_card(request, card_id):
    card = get_object_or_404(Card.all_objects, id=card_id)

    if not card.is_deleted:
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

    now = timezone.now()
    column.is_deleted = True
    column.deleted_at = now
    column.save(update_fields=["is_deleted", "deleted_at"])

    Card.objects.filter(column=column, is_deleted=False).update(is_deleted=True, deleted_at=now)
    return HttpResponse("")


# alias de compatibilidade (se o urls.py ainda usar column_delete)
column_delete = delete_column


# ======================================================================
# MOVER CARD ENTRE COLUNAS
# ======================================================================


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

    if old_column.id == new_column.id:
        cards = list(old_column.cards.order_by("position"))
        cards.remove(card)
        cards.insert(new_position, card)

        for index, c in enumerate(cards):
            if c.position != index:
                c.position = index
                c.save(update_fields=["position"])

        return JsonResponse({"status": "ok"})

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

    return JsonResponse({"status": "ok"})


# ======================================================================
# MODAL DO CARD
# ======================================================================


def card_modal(request, card_id):
    card = get_object_or_404(Card, id=card_id)
    return render(request, "boards/partials/card_modal_body.html", {"card": card})


# ======================================================================
# IMAGEM PRINCIPAL DO BOARD
# ======================================================================


def update_board_image(request, board_id):
    board = get_object_or_404(Board, id=board_id)

    if request.method == "GET":
        return render(request, "boards/partials/board_image_form.html", {"board": board})

    if request.method == "POST":
        if "image" in request.FILES and request.FILES["image"]:
            board.image = request.FILES["image"]
            board.save(update_fields=["image"])
            return HttpResponse('<script>location.reload()</script>')

        url = (request.POST.get("image_url") or "").strip()
        if url:
            try:
                r = requests.get(url, timeout=5)
                if r.status_code == 200:
                    filename = url.split("/")[-1] or "board.jpg"
                    board.image.save(filename, ContentFile(r.content))
                    return HttpResponse('<script>location.reload()</script>')
            except Exception:
                pass

        return HttpResponse("<div class='text-red-600'>Erro ao carregar imagem.</div>", status=400)


@require_POST
def remove_board_image(request, board_id):
    board = get_object_or_404(Board, id=board_id)
    if board.image:
        board.image.delete(save=False)
        board.image = None
        board.save(update_fields=["image"])
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
    tag = request.POST.get("tag", "").strip()
    if not tag:
        return HttpResponse("Tag inválida", status=400)

    old_tags = [t.strip() for t in (card.tags or "").split(",") if t.strip()]
    new_tags = [t for t in old_tags if t != tag]

    if len(old_tags) == len(new_tags):
        return HttpResponse("Tag não encontrada", status=404)

    card.tags = ", ".join(new_tags)
    card.save(update_fields=["tags"])

    CardLog.objects.create(card=card, content=f"Etiqueta removida: {tag}")

    modal_html = render(request, "boards/partials/card_modal_body.html", {"card": card}).content.decode("utf-8")
    snippet_html = render(request, "boards/partials/card_item.html", {"card": card}).content.decode("utf-8")

    return JsonResponse({"modal": modal_html, "snippet": snippet_html, "card_id": card.id})


# ======================================================================
# RENOMEAR BOARD / COLUNA
# ======================================================================


@require_POST
def rename_board(request, board_id):
    board = get_object_or_404(Board, id=board_id)
    name = request.POST.get("name", "").strip()
    if not name:
        return HttpResponse("Nome inválido", status=400)

    board.name = name
    board.save(update_fields=["name"])
    return HttpResponse("OK", status=200)


@require_POST
def rename_column(request, column_id):
    column = get_object_or_404(Column, id=column_id)
    name = request.POST.get("name", "").strip()
    if not name:
        return HttpResponse("Nome inválido", status=400)

    column.name = name
    column.save(update_fields=["name"])
    return render(request, "boards/partials/column_item.html", {"column": column})


# ======================================================================
# WALLPAPER DO BOARD + CSS
# ======================================================================


def update_board_wallpaper(request, board_id):
    board = get_object_or_404(Board, id=board_id)

    if request.method == "GET":
        return render(request, "boards/partials/wallpaper_form.html", {"board": board})

    if request.method == "POST":
        if "image" in request.FILES:
            board.background_image = request.FILES["image"]
            board.background_url = ""
            board.save(update_fields=["background_image", "background_url"])
            return HttpResponse('<script>location.reload()</script>')

        url = request.POST.get("image_url", "").strip()
        if url:
            board.background_url = url
            board.background_image = None
            board.save(update_fields=["background_image", "background_url"])
            return HttpResponse('<script>location.reload()</script>')

        return HttpResponse("Erro", status=400)


def board_wallpaper_css(request, board_id):
    board = get_object_or_404(Board, id=board_id, is_deleted=False)

    css = "body {"
    if getattr(board, "background_image", None):
        css += f"background-image: url('{board.background_image.url}');"
    elif (getattr(board, "background_url", "") or "").strip():
        css += f"background-image: url('{escape(board.background_url)}');"
    else:
        css += "background-image: none;"
        css += "background-color: #f0f0f0;"

    css += """
        background-size: cover;
        background-position: center;
        background-attachment: fixed;
    }
    """

    resp = HttpResponse(css, content_type="text/css")
    resp["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp["Pragma"] = "no-cache"
    resp["Expires"] = "0"
    return resp


@require_POST
def remove_board_wallpaper(request, board_id):
    board = get_object_or_404(Board, id=board_id)

    if board.background_image:
        board.background_image.delete(save=False)
        board.background_image = None

    board.background_url = ""
    board.save(update_fields=["background_image", "background_url"])
    return HttpResponse('<script>location.reload()</script>')


# ======================================================================
# HOME WALLPAPER (Organization.home_wallpaper_filename)
# ======================================================================

HOME_WALLPAPER_FOLDER = os.path.join(settings.MEDIA_ROOT, "home_wallpapers")


def home_wallpaper_css(request):
    css = "body {"

    if request.user.is_authenticated:
        org = get_or_create_user_default_organization(request.user)
        filename = (getattr(org, "home_wallpaper_filename", "") or "").strip()
        if filename:
            css += f'background-image: url("/media/home_wallpapers/{filename}");'
        else:
            css += "background-image: none;"
            css += "background-color: #f0f0f0;"
    else:
        css += "background-image: none;"
        css += "background-color: #f0f0f0;"

    css += """
        background-size: cover;
        background-position: center;
        background-attachment: fixed;
    }
    """

    resp = HttpResponse(css, content_type="text/css")
    resp["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp["Pragma"] = "no-cache"
    resp["Expires"] = "0"
    return resp


def update_home_wallpaper(request):
    os.makedirs(HOME_WALLPAPER_FOLDER, exist_ok=True)

    if request.method == "GET":
        return render(request, "boards/partials/home_wallpaper_form.html", {})

    if not request.user.is_authenticated:
        request.session.pop("home_bg_image", None)
        return HttpResponse("Login necessário.", status=401)

    org = get_or_create_user_default_organization(request.user)
    if not org:
        return HttpResponse("Organização não encontrada.", status=400)

    # Upload
    if "image" in request.FILES:
        file = request.FILES["image"]
        ext = os.path.splitext(file.name or "")[1] or ".jpg"
        filename = f"{uuid.uuid4().hex}{ext}"
        filepath = os.path.join(HOME_WALLPAPER_FOLDER, filename)

        with open(filepath, "wb+") as dest:
            for chunk in file.chunks():
                dest.write(chunk)

        old = (org.home_wallpaper_filename or "").strip()
        if old:
            old_path = os.path.join(HOME_WALLPAPER_FOLDER, old)
            if os.path.exists(old_path):
                try:
                    os.remove(old_path)
                except Exception:
                    pass

        org.home_wallpaper_filename = filename
        org.save(update_fields=["home_wallpaper_filename"])
        return HttpResponse('<script>location.reload()</script>')

    # URL
    url = request.POST.get("image_url", "").strip()
    if url:
        try:
            r = requests.get(url, timeout=8)
            if r.status_code == 200:
                parsed_ext = os.path.splitext(url.split("?")[0])[1] or ".jpg"
                filename = f"{uuid.uuid4().hex}{parsed_ext}"
                filepath = os.path.join(HOME_WALLPAPER_FOLDER, filename)

                with open(filepath, "wb") as f:
                    f.write(r.content)

                old = (org.home_wallpaper_filename or "").strip()
                if old:
                    old_path = os.path.join(HOME_WALLPAPER_FOLDER, old)
                    if os.path.exists(old_path):
                        try:
                            os.remove(old_path)
                        except Exception:
                            pass

                org.home_wallpaper_filename = filename
                org.save(update_fields=["home_wallpaper_filename"])
                return HttpResponse('<script>location.reload()</script>')
        except Exception:
            pass

    return HttpResponse("Erro ao importar imagem", status=400)


def remove_home_wallpaper(request):
    if not request.user.is_authenticated:
        request.session.pop("home_bg_image", None)
        return HttpResponse("Login necessário.", status=401)

    org = get_or_create_user_default_organization(request.user)
    if not org:
        return HttpResponse("Organização não encontrada.", status=400)

    filename = (org.home_wallpaper_filename or "").strip()
    if filename:
        filepath = os.path.join(HOME_WALLPAPER_FOLDER, filename)
        if os.path.exists(filepath):
            try:
                os.remove(filepath)
            except Exception:
                pass

    org.home_wallpaper_filename = ""
    org.save(update_fields=["home_wallpaper_filename"])
    return HttpResponse('<script>location.reload()</script>')


# ======================================================================
# ATIVIDADE NO CARD (Quill) + upload
# ======================================================================


@require_POST
def add_activity(request, card_id):
    card = get_object_or_404(Card, id=card_id)

    raw = request.POST.get("content", "").strip()
    if not raw:
        return HttpResponse("Conteúdo vazio", status=400)

    html = raw

    CardLog.objects.create(
        card=card,
        content=html,
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

    if "file" not in request.FILES:
        return HttpResponse("Nenhum arquivo enviado", status=400)

    uploaded = request.FILES["file"]
    attachment = CardAttachment.objects.create(card=card, file=uploaded)

    CardLog.objects.create(
        card=card,
        content=f"Anexo adicionado: {attachment.file.name.split('/')[-1]}",
        attachment=attachment.file,
    )

    return render(request, "boards/partials/attachment_item.html", {"attachment": attachment})


# ======================================================================
# CHECKLISTS
# ======================================================================


@require_POST
def checklist_add(request, card_id):
    card = get_object_or_404(Card, id=card_id)
    title = request.POST.get("title", "").strip() or "Checklist"
    position = card.checklists.count()

    Checklist.objects.create(card=card, title=title, position=position)
    return render(request, "boards/partials/checklist_list.html", {"card": card})


@require_POST
def checklist_rename(request, checklist_id):
    checklist = get_object_or_404(Checklist, id=checklist_id)
    card = checklist.card

    title = request.POST.get("title", "").strip()
    if title:
        checklist.title = title
        checklist.save(update_fields=["title"])

    return render(request, "boards/partials/checklist_list.html", {"card": card})


@require_POST
def checklist_delete(request, checklist_id):
    checklist = get_object_or_404(Checklist, id=checklist_id)
    card = checklist.card

    checklist.delete()

    for idx, c in enumerate(card.checklists.order_by("position", "created_at")):
        if c.position != idx:
            c.position = idx
            c.save(update_fields=["position"])

    return render(request, "boards/partials/checklist_list.html", {"card": card})


@require_POST
def checklist_add_item(request, checklist_id):
    checklist = get_object_or_404(Checklist, id=checklist_id)
    card = checklist.card

    text = request.POST.get("text", "").strip()
    if not text:
        return HttpResponse("Texto vazio", status=400)

    position = checklist.items.count()
    ChecklistItem.objects.create(card=card, checklist=checklist, text=text, position=position)

    return render(request, "boards/partials/checklist_list.html", {"card": card})


@require_POST
def checklist_toggle_item(request, item_id):
    item = get_object_or_404(ChecklistItem, id=item_id)
    item.is_done = not item.is_done
    item.save(update_fields=["is_done"])
    return render(request, "boards/partials/checklist_item.html", {"item": item})


@require_http_methods(["POST"])
def checklist_delete_item(request, item_id):
    item = get_object_or_404(ChecklistItem, id=item_id)
    card = item.card
    checklist = item.checklist

    item.delete()

    if checklist:
        for idx, it in enumerate(checklist.items.order_by("position", "created_at")):
            if it.position != idx:
                it.position = idx
                it.save(update_fields=["position"])

    return render(request, "boards/partials/checklist_list.html", {"card": card})


@require_POST
def checklist_update_item(request, item_id):
    item = get_object_or_404(ChecklistItem, id=item_id)
    text = request.POST.get("text", "").strip()
    if not text:
        return HttpResponse("Texto vazio", status=400)

    item.text = text
    item.save(update_fields=["text"])
    return render(request, "boards/partials/checklist_item.html", {"item": item})


@require_POST
def checklist_move(request, checklist_id):
    checklist = get_object_or_404(Checklist, id=checklist_id)
    card = checklist.card
    direction = request.POST.get("direction")

    lists_ = list(card.checklists.order_by("position", "created_at"))
    idx = lists_.index(checklist)

    if direction == "up" and idx > 0:
        lists_[idx], lists_[idx - 1] = lists_[idx - 1], lists_[idx]
    elif direction == "down" and idx < len(lists_) - 1:
        lists_[idx], lists_[idx + 1] = lists_[idx + 1], lists_[idx]

    for pos, c in enumerate(lists_):
        if c.position != pos:
            c.position = pos
            c.save(update_fields=["position"])

    return render(request, "boards/partials/checklist_list.html", {"card": card})


@require_POST
def checklist_move_up(request, item_id):
    item = get_object_or_404(ChecklistItem, id=item_id)
    checklist = item.checklist
    card = item.card

    items = list(checklist.items.order_by("position", "created_at"))
    idx = items.index(item)

    if idx > 0:
        items[idx], items[idx - 1] = items[idx - 1], items[idx]

    for pos, it in enumerate(items):
        if it.position != pos:
            it.position = pos
            it.save(update_fields=["position"])

    return render(request, "boards/partials/checklist_list.html", {"card": card})


@require_POST
def checklist_move_down(request, item_id):
    item = get_object_or_404(ChecklistItem, id=item_id)
    checklist = item.checklist
    card = item.card

    items = list(checklist.items.order_by("position", "created_at"))
    idx = items.index(item)

    if idx < len(items) - 1:
        items[idx], items[idx + 1] = items[idx + 1], items[idx]

    for pos, it in enumerate(items):
        if it.position != pos:
            it.position = pos
            it.save(update_fields=["position"])

    return render(request, "boards/partials/checklist_list.html", {"card": card})


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

    identifier = (request.POST.get("identifier") or "").strip()
    role = (request.POST.get("role") or BoardMembership.Role.VIEWER).strip().upper()

    if role not in {BoardMembership.Role.OWNER, BoardMembership.Role.EDITOR, BoardMembership.Role.VIEWER}:
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
