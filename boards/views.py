# ======================================================================
# IMPORTAÇÕES — São as ferramentas que o Python usa para trabalhar aqui
# ======================================================================

from django.shortcuts import render, get_object_or_404, redirect
from django.http import HttpResponse, JsonResponse
from django.views.decorators.http import require_POST
from django.db import transaction
from django.utils import timezone

from .models import Board, Column, Card, CardLog
from .forms import ColumnForm, CardForm, BoardForm

import json
import base64
import re
from django.core.files.base import ContentFile
import requests


# ======================================================================
# FUNÇÃO AUXILIAR — Tirar imagens base64 da descrição do card
# Quem chama? → update_card()
# ======================================================================

def extract_base64_and_convert(html_content):
    """
    Explicação para criança:
    Quando alguém cola uma imagem dentro do card,
    ela vem escondida dentro do texto como base64.
    Essa função pega essa imagem escondida e transforma
    em um arquivo de verdade.
    """

    if not html_content:
        return html_content, None

    pattern = r'<img[^>]+src="data:image\/([a-zA-Z]+);base64,([^"]+)"'
    match = re.search(pattern, html_content)

    if not match:
        return html_content, None

    image_format = match.group(1)
    base64_str = match.group(2)

    try:
        image_data = base64.b64decode(base64_str)
    except:
        return html_content, None

    filename = f"upload.{image_format}"
    file_obj = ContentFile(image_data, name=filename)

    cleaned_html = re.sub(pattern, '', html_content)

    return cleaned_html, file_obj



# ======================================================================
# TELA INICIAL COM TODOS OS BOARDS
# Quem chama? → navegador quando acessa "/"
# ======================================================================

import os
import random
from django.conf import settings

def index(request):
    boards = Board.objects.all()

    # Caminho absoluto da pasta static/images/home/
    home_bg_path = os.path.join(settings.BASE_DIR, "static", "images", "home")

    # Lista todos os arquivos da pasta
    try:
        bg_files = [
            f for f in os.listdir(home_bg_path)
            if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))
        ]
    except FileNotFoundError:
        bg_files = []

    # Escolhe uma imagem aleatória (se existir)
    bg_image = random.choice(bg_files) if bg_files else None

    return render(request, "boards/index.html", {
        "boards": boards,
        "home_bg": True,
        "home_bg_image": bg_image,
    })




# ======================================================================
# DETALHE DE UM BOARD
# Quem chama? → "/board/1/"
# ======================================================================

def board_detail(request, board_id):
    board = get_object_or_404(Board, id=board_id)
    return render(request, "boards/board_detail.html", {"board": board})



# ======================================================================
# ADICIONAR COLUNA
# Quem chama? → botão + coluna (HTMX)
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
# Quem chama? → botão de temas dentro da coluna (HTMX)
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
# ADICIONAR CARD
# Quem chama? → botão "+ Card" (HTMX)
# ======================================================================

def add_card(request, column_id):
    column = get_object_or_404(Column, id=column_id)

    if request.method == "POST":
        form = CardForm(request.POST)
        if form.is_valid():
            card = form.save(commit=False)

            clean_desc, extracted_file = extract_base64_and_convert(card.description or "")
            card.description = clean_desc
            if extracted_file:
                card.attachment = extracted_file

            card.column = column
            card.position = column.cards.count()
            card.save()

            return render(request, "boards/partials/card_item.html", {"card": card})

        return HttpResponse("Erro ao criar card.", status=400)

    return render(
        request,
        "boards/partials/add_card_form.html",
        {"column": column, "form": CardForm()},
    )



# ======================================================================
# ADICIONAR BOARD
# Quem chama? → botão para criar quadro novo
# ======================================================================

def add_board(request):
    if request.method == "POST":
        form = BoardForm(request.POST)
        if form.is_valid():
            board = form.save()
            return HttpResponse(f'<script>window.location.href="/board/{board.id}/"</script>')

        return HttpResponse("Erro ao criar board", status=400)

    return render(request, "boards/partials/add_board_form.html", {"form": BoardForm()})



# ======================================================================
# EDITAR CARD (abre modal)
# Quem chama? → clique no card (HTMX GET)
# ======================================================================

def edit_card(request, card_id):
    card = get_object_or_404(Card, id=card_id)

    if request.method == "POST":
        form = CardForm(request.POST, request.FILES, instance=card)

        if form.is_valid():
            form.save()

            CardLog.objects.create(
                card=card,
                content=card.description,
                attachment=card.attachment
            )

            return render(request, "boards/partials/card_modal_body.html", {"card": card})

    else:
        form = CardForm(instance=card)

    return render(
        request,
        "boards/partials/card_edit_form.html",
        {"card": card, "form": form},
    )



# ======================================================================
# ATUALIZAR CARD
# Quem chama? → salvar modal do card (HTMX POST)
# ======================================================================

@require_POST
def update_card(request, card_id):
    card = get_object_or_404(Card, id=card_id)

    card.title = request.POST.get("title", card.title)

    raw_desc = request.POST.get("description", card.description or "")
    clean_desc, extracted_file = extract_base64_and_convert(raw_desc)
    card.description = clean_desc

    old_tags_raw = card.tags or ""
    new_tags_raw = request.POST.get("tags", old_tags_raw) or ""

    old_tags = [t.strip() for t in old_tags_raw.split(",") if t.strip()]
    new_tags = [t.strip() for t in new_tags_raw.split(",") if t.strip()]

    card.tags = new_tags_raw

    removed = [t for t in old_tags if t not in new_tags]
    added = [t for t in new_tags if t not in old_tags]

    if "attachment" in request.FILES and request.FILES["attachment"]:
        card.attachment = request.FILES["attachment"]

    if extracted_file:
        card.attachment = extracted_file

    card.save()

    if removed:
        for t in removed:
            CardLog.objects.create(card=card, content=f"Etiqueta removida: {t}")

    if added:
        for t in added:
            CardLog.objects.create(card=card, content=f"Etiqueta adicionada: {t}")

    if not added and not removed:
        CardLog.objects.create(
            card=card,
            content="Card atualizado.",
            attachment=card.attachment if card.attachment else None,
        )

    return render(request, "boards/partials/card_modal_body.html", {"card": card})



# ======================================================================
# DELETAR CARD
# Quem chama? → botão remover card (HTMX POST)
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
# DELETAR COLUNA
# Quem chama? → botão excluir coluna (HTMX POST)
# ======================================================================

@require_POST
def delete_column(request, column_id):
    column = get_object_or_404(Column, id=column_id)

    if column.cards.exists():
        return JsonResponse(
            {"error": "A coluna possui cards e não pode ser excluída."},
            status=400
        )

    column.delete()
    return HttpResponse(status=204)



# ======================================================================
# MOVER CARD ENTRE COLUNAS
# Quem chama? → arrastar card com SortableJS (AJAX POST)
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
# Quem chama? → clique no card (HTMX GET)
# ======================================================================

def card_modal(request, card_id):
    card = get_object_or_404(Card, id=card_id)
    return render(request, "boards/partials/card_modal_body.html", {"card": card})



# ======================================================================
# ATUALIZAR IMAGEM PRINCIPAL DO BOARD
# Quem chama? → clique no logo do board (HTMX)
# ======================================================================

def update_board_image(request, board_id):
    board = get_object_or_404(Board, id=board_id)

    if request.method == "GET":
        return render(request, "boards/partials/board_image_form.html", {"board": board})

    if request.method == "POST":

        if "image" in request.FILES and request.FILES["image"]:
            board.image = request.FILES["image"]
            board.save()
            return HttpResponse('<script>location.reload()</script>')

        url = request.POST.get("image_url")
        if url:
            try:
                r = requests.get(url, timeout=5)
                if r.status_code == 200:
                    filename = url.split("/")[-1]
                    board.image.save(filename, ContentFile(r.content))
                    return HttpResponse('<script>location.reload()</script>')
            except:
                pass

        return HttpResponse(
            "<div class='text-red-600'>Erro ao carregar imagem.</div>",
            status=400
        )



# ======================================================================
# REMOVER IMAGEM PRINCIPAL DO BOARD
# Quem chama? → botão X na imagem do board (HTMX)
# ======================================================================

@require_POST
def remove_board_image(request, board_id):
    board = get_object_or_404(Board, id=board_id)

    if board.image:
        board.image.delete(save=False)
        board.image = None
        board.save(update_fields=["image"])

    return HttpResponse('<script>location.reload()</script>')



# ======================================================================
# REMOVER ANEXO DO CARD
# Quem chama? → botão excluir anexo no modal
# ======================================================================

@require_POST
def delete_attachment(request, card_id):
    card = get_object_or_404(Card, id=card_id)

    if not card.attachment:
        return HttpResponse("No attachment", status=204)

    CardLog.objects.create(
        card=card,
        content="Anexo removido",
        attachment=None
    )

    card.attachment.delete(save=False)
    card.attachment = None
    card.save(update_fields=["attachment"])

    return render(request, "boards/partials/card_modal_body.html", {"card": card})



# ======================================================================
# ATUALIZAR SOMENTE O CARD (SNIPPET)
# Quem chama? → atualização de card após salvar modal
# ======================================================================

def card_snippet(request, card_id):
    card = get_object_or_404(Card, id=card_id)
    return render(request, "boards/partials/card_item.html", {"card": card})



# ======================================================================
# REMOVER TAG
# Quem chama? → botão X das tags dentro do modal do card
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

    CardLog.objects.create(
        card=card,
        content=f"Etiqueta removida: {tag}"
    )

    modal_html = render(
        request,
        "boards/partials/card_modal_body.html",
        {"card": card}
    ).content.decode("utf-8")

    snippet_html = render(
        request,
        "boards/partials/card_item.html",
        {"card": card}
    ).content.decode("utf-8")

    return JsonResponse({
        "modal": modal_html,
        "snippet": snippet_html,
        "card_id": card.id
    })



# ======================================================================
# RENOMEAR BOARD
# Quem chama? → editar nome do board (contenteditable)
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



# ======================================================================
# RENOMEAR COLUNA
# Quem chama? → editar título da coluna (contenteditable)
# ======================================================================

@require_POST
def rename_column(request, column_id):
    column = get_object_or_404(Column, id=       column_id)
    name = request.POST.get("name", "").strip()

    if not name:
        return HttpResponse("Nome inválido", status=400)

    column.name = name
    column.save(update_fields=["name"])

    return render(request, "boards/partials/column_item.html", {"column": column})



# ======================================================================
# UPDATE WALLPAPER — ESTA É A FUNÇÃO QUE O MENU HAMBURGUER USA
# Quem chama? → botão "Trocar Wallpaper" do menu (HTMX GET)
#                submit do modal (HTMX POST)
# ======================================================================

def update_board_wallpaper(request, board_id):
    board = get_object_or_404(Board, id=board_id)

    # Quando a pessoa clica em "Trocar Wallpaper"
    if request.method == "GET":
        return render(request, "boards/partials/wallpaper_form.html", {"board": board})

    # Quando clica em "Salvar" no modal
    if request.method == "POST":

        # Upload de arquivo
        if "image" in request.FILES:
            board.background_image = request.FILES["image"]
            board.background_url = ""
            board.save()
            return HttpResponse('<script>location.reload()</script>')

        # URL da imagem
        url = request.POST.get("image_url", "").strip()
        if url:
            board.background_url = url
            board.background_image = None
            board.save()
            return HttpResponse('<script>location.reload()</script>')

        return HttpResponse("Erro", status=400)



# ======================================================================
# REMOVER WALLPAPER
# Quem chama? → botão vermelho "Remover papel de parede"
# ======================================================================

@require_POST
def remove_board_wallpaper(request, board_id):
    board = get_object_or_404(Board, id=board_id)
    board.background_image = None
    board.background_url = ""
    board.save()
    return HttpResponse('<script>location.reload()</script>')


def board_wallpaper_css(request, board_id):
    board = Board.objects.get(id=board_id)

    css = "body {"

    # background a partir do upload
    if board.background_image and board.background_image.name:
        css += f'background-image: url("{board.background_image.url}");'

    # background a partir de URL externa
    elif board.background_url:
        css += f'background-image: url("{board.background_url}");'

    # caso não tenha wallpaper
    else:
        css += 'background-color: #f0f0f0;'

    css += """
        background-size: cover;
        background-position: center;
        background-attachment: fixed;
    }
    """

    return HttpResponse(css, content_type="text/css")


# ---------------- HOME WALLPAPER ----------------

from django.conf import settings
import os

HOME_WALLPAPER_FOLDER = os.path.join(settings.MEDIA_ROOT, "home_wallpapers")

def update_home_wallpaper(request):

    os.makedirs(HOME_WALLPAPER_FOLDER, exist_ok=True)

    if request.method == "GET":
        return render(request, "boards/partials/home_wallpaper_form.html", {})

    # Upload
    if "image" in request.FILES:
        file = request.FILES["image"]
        filepath = os.path.join(HOME_WALLPAPER_FOLDER, file.name)

        # salva novo papel de parede
        with open(filepath, "wb+") as dest:
            for chunk in file.chunks():
                dest.write(chunk)

        request.session["home_wallpaper"] = file.name
        return HttpResponse('<script>location.reload()</script>')

    # URL externa
    url = request.POST.get("image_url", "").strip()
    if url:
        try:
            r = requests.get(url, timeout=5)
            if r.status_code == 200:
                filename = url.split("/")[-1]
                filepath = os.path.join(HOME_WALLPAPER_FOLDER, filename)
                with open(filepath, "wb") as f:
                    f.write(r.content)

                request.session["home_wallpaper"] = filename
                return HttpResponse('<script>location.reload()</script>')
        except:
            pass

    return HttpResponse("Erro ao importar imagem", status=400)



def remove_home_wallpaper(request):
    filename = request.session.get("home_wallpaper")

    if filename:
        filepath = os.path.join(HOME_WALLPAPER_FOLDER, filename)
        if os.path.exists(filepath):
            os.remove(filepath)

    request.session["home_wallpaper"] = None
    return HttpResponse('<script>location.reload()</script>')



def home_wallpaper_css(request):
    filename = request.session.get("home_wallpaper")

    css = "body {"

    if filename:
        css += f'background-image: url("/media/home_wallpapers/{filename}");'
    else:
        css += "background-color: #f0f0f0;"

    css += """
        background-size: cover;
        background-position: center;
        background-attachment: fixed;
    }
    """

    return HttpResponse(css, content_type="text/css")


# ======================================================================
# ADICIONAR ATIVIDADE NO CARD
# Quem chama? → submitActivity() via HTMX POST
# ======================================================================

from django.views.decorators.http import require_POST

@require_POST
def add_activity(request, card_id):
    card = get_object_or_404(Card, id=card_id)

    content = request.POST.get("content", "").strip()

    if not content:
        return HttpResponse("Conteúdo vazio", status=400)

    # salva no log
    CardLog.objects.create(
        card=card,
        content=content,
        attachment=None
    )

    # retorna apenas a aba de atividades
    html = render(
        request,
        "boards/partials/card_activity_panel.html",
        {"card": card}
    ).content.decode("utf-8")

    return HttpResponse(html)

# ======================================================================
# ADICIONAR ATIVIDADE NO CARD
# Quem chama? → submitActivity() via HTMX POST
# ======================================================================

@require_POST
def add_activity(request, card_id):
    card = get_object_or_404(Card, id=card_id)

    content = request.POST.get("content", "").strip()
    if not content:
        return HttpResponse("Conteúdo vazio", status=400)

    CardLog.objects.create(
        card=card,
        content=content,
        attachment=None
    )

    html = render(
        request,
        "boards/partials/card_activity_panel.html",
        {"card": card}
    ).content.decode("utf-8")

    return HttpResponse(html)
