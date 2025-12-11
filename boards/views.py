# ======================================================================
# IMPORTAÇÕES — São as ferramentas que o Python usa para trabalhar aqui
# ======================================================================

import os
import random
import json
import base64
import re
import requests

from django.conf import settings
from django.shortcuts import render, get_object_or_404, redirect
from django.http import HttpResponse, JsonResponse
from django.views.decorators.http import require_POST, require_http_methods
from django.db import transaction
from django.utils import timezone
from django.utils.html import escape
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.views.decorators.csrf import csrf_exempt

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

    # nome amigável para o workspace
    display_name = user.get_full_name() or user.get_username() or str(user)

    org, created = Organization.objects.get_or_create(
        owner=user,
        defaults={
            "name": f"Workspace de {display_name}",
        },
    )

    # garante membership como OWNER
    OrganizationMembership.objects.get_or_create(
        organization=org,
        user=user,
        defaults={"role": OrganizationMembership.Role.OWNER},
    )

    return org


# ======================================================================
# FUNÇÃO AUXILIAR — Tirar imagens base64 da descrição do card
# Quem chama? → update_card()
# ======================================================================

def extract_base64_and_convert(html_content):
    """
    Quando alguém cola uma imagem dentro do card,
    ela vem escondida dentro do texto como base64.
    Esta função extrai essa imagem e devolve:
      - html limpo (sem o <img> base64)
      - arquivo Django (ContentFile) ou None
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
    except Exception:
        return html_content, None

    filename = f"upload.{image_format}"
    file_obj = ContentFile(image_data, name=filename)

    cleaned_html = re.sub(pattern, "", html_content)

    return cleaned_html, file_obj


# ======================================================================
# TELA INICIAL COM TODOS OS BOARDS
# Quem chama? → navegador quando acessa "/"
# ======================================================================

def index(request):
    # Se o usuário estiver autenticado, mostra apenas boards onde ele é membro.
    if request.user.is_authenticated:
        boards = (
            Board.objects.filter(
                is_deleted=False,
                memberships__user=request.user,
            )
            .distinct()
        )
    else:
        # Cenário legado / anônimo: mantém visibilidade global por enquanto
        boards = Board.objects.filter(is_deleted=False)

    home_bg_path = os.path.join(settings.BASE_DIR, "static", "images", "home")

    try:
        bg_files = [
            f
            for f in os.listdir(home_bg_path)
            if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))
        ]
    except FileNotFoundError:
        bg_files = []

    bg_image = random.choice(bg_files) if bg_files else None

    return render(
        request,
        "boards/index.html",
        {
            "boards": boards,
            "home_bg": True,
            "home_bg_image": bg_image,
        },
    )



# ======================================================================
# DETALHE DE UM BOARD
# Quem chama? → "/board/1/"
# ======================================================================

def board_detail(request, board_id):
    board = get_object_or_404(Board, id=board_id, is_deleted=False)

    # Estratégia de transição:
    # - Se o board já tiver memberships, aplicamos controle de acesso.
    # - Se NÃO tiver memberships, tratamos como legado (acesso aberto).
    memberships_qs = board.memberships.select_related("user")

    if memberships_qs.exists():
        if not request.user.is_authenticated:
            return HttpResponse("Você não tem acesso a este quadro.", status=403)

        if not memberships_qs.filter(user=request.user).exists():
            return HttpResponse("Você não tem acesso a este quadro.", status=403)

    columns = board.columns.filter(is_deleted=False).order_by("position")

    return render(
        request,
        "boards/board_detail.html",
        {"board": board, "columns": columns},
    )



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

            return render(
                request,
                "boards/partials/column_item.html",
                {"column": column},
            )

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

            clean_desc, extracted_file = extract_base64_and_convert(
                card.description or ""
            )
            card.description = clean_desc
            if extracted_file:
                # se ainda existir attachment único no modelo
                card.attachment = extracted_file

            card.column = column
            card.position = column.cards.count()
            card.save()

            return render(
                request,
                "boards/partials/card_item.html",
                {"card": card},
            )

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
            board = form.save(commit=False)

            # Se estiver autenticado, amarramos:
            # - quem criou
            # - qual organização é dona
            if request.user.is_authenticated:
                board.created_by = request.user
                org = get_or_create_user_default_organization(request.user)
                board.organization = org

            board.save()

            # Cria membership do criador como OWNER (quando autenticado)
            if request.user.is_authenticated:
                BoardMembership.objects.get_or_create(
                    board=board,
                    user=request.user,
                    defaults={"role": BoardMembership.Role.OWNER},
                )

            return HttpResponse(
                f'<script>window.location.href="/board/{board.id}/"</script>'
            )

        return HttpResponse("Erro ao criar board", status=400)

    return render(
        request,
        "boards/partials/add_board_form.html",
        {"form": BoardForm()},
    )


# ============================================================
#   SOFT DELETE DE QUADRO (BOARD)
# ============================================================

from django.utils import timezone
from django.http import HttpResponseBadRequest, HttpResponse

def delete_board(request, board_id):
    if request.method != "POST":
        return HttpResponseBadRequest("Método inválido.")

    try:
        board = Board.objects.get(id=board_id, is_deleted=False)
    except Board.DoesNotExist:
        return HttpResponseBadRequest("Quadro não encontrado.")

    # marca o board como removido
    board.is_deleted = True
    board.deleted_at = timezone.now()
    board.save()

    # desativar colunas e cards ligados
    Column.objects.filter(board=board, is_deleted=False).update(
        is_deleted=True,
        deleted_at=timezone.now()
    )

    Card.objects.filter(column__board=board, is_deleted=False).update(
        is_deleted=True,
        deleted_at=timezone.now()
    )

    # retorno vazio para HTMX remover o card visual da home
    return HttpResponse("")


# ======================================================================
# EDITAR CARD (abre modal antigo de formulário)
# Hoje o modal principal usa card_modal + card_modal_content
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
                attachment=getattr(card, "attachment", None),
            )

            return render(
                request,
                "boards/partials/card_modal_body.html",
                {"card": card},
            )

    else:
        form = CardForm(instance=card)

    return render(
        request,
        "boards/partials/card_edit_form.html",
        {"card": card, "form": form},
    )


# ======================================================================
# ATUALIZAR CARD (modal novo)
# Quem chama? → salvar modal do card (HTMX POST)
# ======================================================================

@require_POST
def update_card(request, card_id):
    card = get_object_or_404(Card, id=card_id)

    # título
    card.title = request.POST.get("title", card.title)

    # descrição (com eventual base64)
    raw_desc = request.POST.get("description", card.description or "")
    clean_desc, extracted_file = extract_base64_and_convert(raw_desc)
    card.description = clean_desc

    # tags
    old_tags_raw = card.tags or ""
    new_tags_raw = request.POST.get("tags", old_tags_raw) or ""

    old_tags = [t.strip() for t in old_tags_raw.split(",") if t.strip()]
    new_tags = [t.strip() for t in new_tags_raw.split(",") if t.strip()]

    card.tags = new_tags_raw

    removed = [t for t in old_tags if t not in new_tags]
    added = [t for t in new_tags if t not in old_tags]

    # anexo único (se ainda existir no modelo)
    if "attachment" in request.FILES and request.FILES["attachment"]:
        card.attachment = request.FILES["attachment"]

    if extracted_file:
        card.attachment = extracted_file

    card.save()

    # logs de tags
    if removed:
        for t in removed:
            CardLog.objects.create(card=card, content=f"Etiqueta removida: {t}")

    if added:
        for t in added:
            CardLog.objects.create(card=card, content=f"Etiqueta adicionada: {t}")

    # log genérico
    if not added and not removed:
        CardLog.objects.create(
            card=card,
            content="Card atualizado.",
            attachment=getattr(card, "attachment", None),
        )

    return render(
        request,
        "boards/partials/card_modal_body.html",
        {"card": card},
    )


# ======================================================================
# DELETAR CARD (lixeira lógica)
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

    # Não pode deletar se possui cards ativos
    if column.cards.exists():
        return JsonResponse(
            {"error": "A coluna possui cards e não pode ser excluída."},
            status=400,
        )

    if not column.is_deleted:
        column.is_deleted = True
        column.deleted_at = timezone.now()
        column.save(update_fields=["is_deleted", "deleted_at"])

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

    # mesma coluna → apenas reordenar
    if old_column.id == new_column.id:
        cards = list(old_column.cards.order_by("position"))
        cards.remove(card)
        cards.insert(new_position, card)

        for index, c in enumerate(cards):
            if c.position != index:
                c.position = index
                c.save(update_fields=["position"])

        return JsonResponse({"status": "ok"})

    # coluna antiga
    old_cards = list(old_column.cards.exclude(id=card.id).order_by("position"))
    for index, c in enumerate(old_cards):
        if c.position != index:
            c.position = index
            c.save(update_fields=["position"])

    # move card
    card.column = new_column
    card.save(update_fields=["column"])

    # coluna nova
    new_cards = list(new_column.cards.order_by("position"))
    new_cards.insert(new_position, card)

    for index, c in enumerate(new_cards):
        if c.position != index:
            c.position = index
            c.save(update_fields=["position"])

    return JsonResponse({"status": "ok"})


# ======================================================================
# MODAL DO CARD (wrapper do body)
# Quem chama? → clique no card (HTMX GET)
# ======================================================================

def card_modal(request, card_id):
    card = get_object_or_404(Card, id=card_id)
    return render(
        request,
        "boards/partials/card_modal_body.html",
        {"card": card},
    )


# ======================================================================
# ATUALIZAR IMAGEM PRINCIPAL DO BOARD
# Quem chama? → clique no logo do board (HTMX)
# ======================================================================

def update_board_image(request, board_id):
    board = get_object_or_404(Board, id=board_id)

    if request.method == "GET":
        return render(
            request,
            "boards/partials/board_image_form.html",
            {"board": board},
        )

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
            except Exception:
                pass

        return HttpResponse(
            "<div class='text-red-600'>Erro ao carregar imagem.</div>",
            status=400,
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
# REMOVER ANEXO DO CARD (antigo attachment único)
# Quem chama? → botão excluir anexo no modal
# ======================================================================

@require_POST
def delete_attachment(request, card_id):
    card = get_object_or_404(Card, id=card_id)

    if not getattr(card, "attachment", None):
        return HttpResponse("No attachment", status=204)

    CardLog.objects.create(
        card=card,
        content="Anexo removido",
        attachment=None,
    )

    card.attachment.delete(save=False)
    card.attachment = None
    card.save(update_fields=["attachment"])

    return render(
        request,
        "boards/partials/card_modal_body.html",
        {"card": card},
    )


# ======================================================================
# ATUALIZAR SOMENTE O CARD (SNIPPET)
# Quem chama? → atualização de card após salvar modal
# ======================================================================

def card_snippet(request, card_id):
    card = get_object_or_404(Card, id=card_id)
    return render(
        request,
        "boards/partials/card_item.html",
        {"card": card},
    )


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

    CardLog.objects.create(card=card, content=f"Etiqueta removida: {tag}")

    modal_html = render(
        request,
        "boards/partials/card_modal_body.html",
        {"card": card},
    ).content.decode("utf-8")

    snippet_html = render(
        request,
        "boards/partials/card_item.html",
        {"card": card},
    ).content.decode("utf-8")

    return JsonResponse(
        {
            "modal": modal_html,
            "snippet": snippet_html,
            "card_id": card.id,
        }
    )


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
    column = get_object_or_404(Column, id=column_id)
    name = request.POST.get("name", "").strip()

    if not name:
        return HttpResponse("Nome inválido", status=400)

    column.name = name
    column.save(update_fields=["name"])

    return render(
        request,
        "boards/partials/column_item.html",
        {"column": column},
    )


# ======================================================================
# UPDATE WALLPAPER DO BOARD
# Quem chama? → botão "Trocar Wallpaper"
# ======================================================================

def update_board_wallpaper(request, board_id):
    board = get_object_or_404(Board, id=board_id)

    if request.method == "GET":
        return render(
            request,
            "boards/partials/wallpaper_form.html",
            {"board": board},
        )

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
# REMOVER WALLPAPER DO BOARD
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

    if board.background_image and board.background_image.name:
        css += f'background-image: url("{board.background_image.url}");'
    elif board.background_url:
        css += f'background-image: url("{board.background_url}");'
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
# WALLPAPER DA HOME
# ======================================================================

HOME_WALLPAPER_FOLDER = os.path.join(settings.MEDIA_ROOT, "home_wallpapers")


def update_home_wallpaper(request):
    os.makedirs(HOME_WALLPAPER_FOLDER, exist_ok=True)

    if request.method == "GET":
        return render(
            request,
            "boards/partials/home_wallpaper_form.html",
            {},
        )

    if "image" in request.FILES:
        file = request.FILES["image"]
        filepath = os.path.join(HOME_WALLPAPER_FOLDER, file.name)

        with open(filepath, "wb+") as dest:
            for chunk in file.chunks():
                dest.write(chunk)

        request.session["home_wallpaper"] = file.name
        return HttpResponse('<script>location.reload()</script>')

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
        except Exception:
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
# ADICIONAR ATIVIDADE NO CARD – via Quill
# ======================================================================

@require_POST
def add_activity(request, card_id):
    card = get_object_or_404(Card, id=card_id)

    raw = request.POST.get("content", "").strip()
    if not raw:
        return HttpResponse("Conteúdo vazio", status=400)

    html = raw  # já vem como HTML do Quill

    CardLog.objects.create(
        card=card,
        content=html,
        attachment=None,
    )

    # extrai <img src="..."> e cria CardAttachment quando forem de /media/quill/
    img_urls = re.findall(r'src="([^"]+)"', html)

    for url in img_urls:
        if "/media/quill/" not in url:
            continue

        relative_path = url.split("/media/")[-1]

        if card.attachments.filter(file=relative_path).exists():
            continue

        CardAttachment.objects.create(
            card=card,
            file=relative_path,
        )

    rendered = render(
        request,
        "boards/partials/card_activity_panel.html",
        {"card": card},
    ).content.decode("utf-8")

    return HttpResponse(rendered)


# ============================================================
# UPLOAD DE IMAGEM PARA O QUILL
# ============================================================

@csrf_exempt
def quill_upload(request):
    """
    Endpoint para upload real de imagens enviadas pelo Quill.
    Recebe um arquivo, salva em /media/quill/, retorna a URL.
    """
    if request.method != "POST" or "image" not in request.FILES:
        return JsonResponse({"error": "Invalid request"}, status=400)

    img = request.FILES["image"]
    file_path = default_storage.save(f"quill/{img.name}", ContentFile(img.read()))
    file_url = default_storage.url(file_path)

    return JsonResponse({"success": 1, "url": file_url})


# ======================================================================
# ANEXOS MÚLTIPLOS (CardAttachment)
# ======================================================================

@require_POST
def add_attachment(request, card_id):
    card = get_object_or_404(Card, id=card_id)

    if "file" not in request.FILES:
        return HttpResponse("Nenhum arquivo enviado", status=400)

    uploaded = request.FILES["file"]

    attachment = CardAttachment.objects.create(
        card=card,
        file=uploaded,
    )

    CardLog.objects.create(
        card=card,
        content=f"Anexo adicionado: {attachment.file.name.split('/')[-1]}",
        attachment=attachment.file,
    )

    return render(
        request,
        "boards/partials/attachment_item.html",
        {"attachment": attachment},
    )


# ============================================================
# CHECKLISTS – múltiplos por card
# ============================================================

@require_POST
def checklist_add(request, card_id):
    """
    Cria um novo checklist dentro do card.
    """
    card = get_object_or_404(Card, id=card_id)

    title = request.POST.get("title", "").strip() or "Checklist"
    position = card.checklists.count()

    Checklist.objects.create(
        card=card,
        title=title,
        position=position,
    )

    return render(
        request,
        "boards/partials/checklist_list.html",
        {"card": card},
    )


@require_POST
def checklist_rename(request, checklist_id):
    checklist = get_object_or_404(Checklist, id=checklist_id)
    card = checklist.card

    title = request.POST.get("title", "").strip()
    if title:
        checklist.title = title
        checklist.save(update_fields=["title"])

    return render(
        request,
        "boards/partials/checklist_list.html",
        {"card": card},
    )


@require_POST
def checklist_delete(request, checklist_id):
    checklist = get_object_or_404(Checklist, id=checklist_id)
    card = checklist.card

    checklist.delete()

    # Recompacta posições das listas
    for idx, c in enumerate(card.checklists.order_by("position", "created_at")):
        if c.position != idx:
            c.position = idx
            c.save(update_fields=["position"])

    return render(
        request,
        "boards/partials/checklist_list.html",
        {"card": card},
    )


@require_POST
def checklist_add_item(request, checklist_id):
    """
    Adiciona item dentro de um checklist específico.
    """
    checklist = get_object_or_404(Checklist, id=checklist_id)
    card = checklist.card

    text = request.POST.get("text", "").strip()
    if not text:
        return HttpResponse("Texto vazio", status=400)

    position = checklist.items.count()

    ChecklistItem.objects.create(
        card=card,
        checklist=checklist,
        text=text,
        position=position,
    )

    return render(
        request,
        "boards/partials/checklist_list.html",
        {"card": card},
    )


@require_POST
def checklist_toggle_item(request, item_id):
    """
    Marca / desmarca como concluído.
    """
    item = get_object_or_404(ChecklistItem, id=item_id)

    item.is_done = not item.is_done
    item.save(update_fields=["is_done"])

    return render(
        request,
        "boards/partials/checklist_item.html",
        {"item": item},
    )


@require_http_methods(["POST"])
def checklist_delete_item(request, item_id):
    """
    Remove um item do checklist e recompacta posições.
    """
    item = get_object_or_404(ChecklistItem, id=item_id)
    card = item.card
    checklist = item.checklist

    item.delete()

    if checklist:
        for idx, it in enumerate(
            checklist.items.order_by("position", "created_at")
        ):
            if it.position != idx:
                it.position = idx
                it.save(update_fields=["position"])

    return render(
        request,
        "boards/partials/checklist_list.html",
        {"card": card},
    )


@require_POST
def checklist_update_item(request, item_id):
    """
    Atualiza o texto de um item (edição inline).
    """
    item = get_object_or_404(ChecklistItem, id=item_id)
    text = request.POST.get("text", "").strip()

    if not text:
        return HttpResponse("Texto vazio", status=400)

    item.text = text
    item.save(update_fields=["text"])

    return render(
        request,
        "boards/partials/checklist_item.html",
        {"item": item},
    )


@require_POST
def checklist_move(request, checklist_id):
    """
    Move checklist (lista) para cima/baixo.
    Espera direction = 'up' ou 'down'.
    """
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

    return render(
        request,
        "boards/partials/checklist_list.html",
        {"card": card},
    )


@require_POST
def checklist_move_up(request, item_id):
    """
    Move item uma posição para cima dentro do checklist.
    """
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

    return render(
        request,
        "boards/partials/checklist_list.html",
        {"card": card},
    )


@require_POST
def checklist_move_down(request, item_id):
    """
    Move item uma posição para baixo dentro do checklist.
    """
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

    return render(
        request,
        "boards/partials/checklist_list.html",
        {"card": card},
    )

from django.utils import timezone
from django.http import HttpResponseBadRequest, HttpResponse
from .models import Column, Card

# ============================================================
# SOFT DELETE DE COLUNA
# ============================================================
def column_delete(request, column_id):
    if request.method != "POST":
        return HttpResponseBadRequest("Método inválido.")

    try:
        column = Column.objects.get(id=column_id, is_deleted=False)
    except Column.DoesNotExist:
        return HttpResponseBadRequest("Coluna não encontrada.")

    # Soft delete da coluna
    column.is_deleted = True
    column.deleted_at = timezone.now()
    column.save()

    # Soft delete dos cards vinculados
    Card.objects.filter(column=column, is_deleted=False).update(
        is_deleted=True,
        deleted_at=timezone.now()
    )

    return HttpResponse("")

# ============================================================
# SOFT DELETE DE COLUNA
# ============================================================
def delete_column(request, column_id):
    if request.method != "POST":
        return HttpResponseBadRequest("Método inválido.")

    try:
        column = Column.objects.get(id=column_id, is_deleted=False)
    except Column.DoesNotExist:
        return HttpResponseBadRequest("Coluna não encontrada.")

    # Soft delete da coluna
    column.is_deleted = True
    column.deleted_at = timezone.now()
    column.save()

    # Soft delete dos cards vinculados
    Card.objects.filter(column=column, is_deleted=False).update(
        is_deleted=True,
        deleted_at=timezone.now()
    )

    return HttpResponse("")


@require_POST
def delete_card(request, card_id):
    card = get_object_or_404(Card.all_objects, id=card_id)

    if not card.is_deleted:
        card.is_deleted = True
        card.deleted_at = timezone.now()
        card.save(update_fields=["is_deleted", "deleted_at"])

    return HttpResponse("", status=200)
