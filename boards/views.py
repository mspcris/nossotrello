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


# ============================================================
# UTILITÁRIO: remover base64 de descrição e criar arquivo real
# ============================================================

def extract_base64_and_convert(html_content):
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


# ============================================================
# HOME: lista boards
# ============================================================

def index(request):
    boards = Board.objects.all()
    return render(request, "boards/index.html", {"boards": boards})


# ============================================================
# DETALHE DO BOARD
# ============================================================

def board_detail(request, board_id):
    board = get_object_or_404(Board, id=board_id)
    return render(request, "boards/board_detail.html", {"board": board})


# ============================================================
# ADICIONAR COLUNA
# ============================================================

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


# ============================================================
# SET COLUMN THEME (NOVO)
# ============================================================

@require_POST
def set_column_theme(request, column_id):
    column = get_object_or_404(Column, id=column_id)
    theme = request.POST.get("theme")

    # valida
    valid_themes = [t[0] for t in Column.THEME_CHOICES]
    if theme not in valid_themes:
        return HttpResponse("Tema inválido", status=400)

    # salva
    column.theme = theme
    column.save(update_fields=["theme"])

    # retorna a coluna inteira refeita (card_item inclui hx-swap="outerHTML")
    return render(
        request,
        "boards/partials/column_item.html",
        {"column": column},
    )


# ============================================================
# ADICIONAR CARD
# ============================================================

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


# ============================================================
# ADICIONAR BOARD
# ============================================================

def add_board(request):
    if request.method == "POST":
        form = BoardForm(request.POST)
        if form.is_valid():
            board = form.save()
            return HttpResponse(
                f'<script>window.location.href="/board/{board.id}/"</script>'
            )

        return HttpResponse("Erro ao criar board", status=400)

    return render(request, "boards/partials/add_board_form.html", {"form": BoardForm()})


# ============================================================
# EDITAR CARD (modal)
# ============================================================

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


# ============================================================
# UPDATE CARD
# ============================================================

@require_POST
def update_card(request, card_id):
    card = get_object_or_404(Card, id=card_id)

    # TÍTULO
    card.title = request.POST.get("title", card.title)

    # DESCRIÇÃO (fixa, não vai pro log em HTML)
    raw_desc = request.POST.get("description", card.description or "")
    clean_desc, extracted_file = extract_base64_and_convert(raw_desc)
    card.description = clean_desc

    # TAGS
    card.tags = request.POST.get("tags", card.tags)

    # ANEXO (upload normal)
    if "attachment" in request.FILES and request.FILES["attachment"]:
        card.attachment = request.FILES["attachment"]

    # ANEXO via imagem colada (base64)
    if extracted_file:
        card.attachment = extracted_file

    card.save()

    # LOG: mensagem curta, sem despejar a descrição inteira
    CardLog.objects.create(
        card=card,
        content="Card atualizado (título/descrição/etiquetas/anexos).",
        attachment=card.attachment if card.attachment else None,
    )

    # Re-renderiza o corpo do modal (agora com abas)
    return render(
        request,
        "boards/partials/card_modal_body.html",
        {"card": card},
    )


# ============================================================
# DELETE CARD — SOFT DELETE + SUMIR NA HORA
# ============================================================

@require_POST
def delete_card(request, card_id):
    card = get_object_or_404(Card.all_objects, id=card_id)

    if not card.is_deleted:
        card.is_deleted = True
        card.deleted_at = timezone.now()
        card.save(update_fields=["is_deleted", "deleted_at"])

    # IMPORTANTE: retornar 200 com string vazia para o HTMX
    return HttpResponse("", status=200)


# ============================================================
# DELETE COLUMN
# ============================================================

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


# ============================================================
# MOVER CARD
# ============================================================

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


# ============================================================
# MODAL DO CARD
# ============================================================

def card_modal(request, card_id):
    card = get_object_or_404(Card, id=card_id)
    return render(request, "boards/partials/card_modal_body.html", {"card": card})


# ============================================================
# UPDATE BOARD IMAGE
# ============================================================

import requests
from django.core.files.base import ContentFile

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
            """
            <div class='bg-red-100 border border-red-400 text-red-700 px-4 py-2 rounded mb-3'>
                Não foi possível carregar esta imagem. Verifique o arquivo ou URL.
            </div>
            """,
            status=400
        )


# ============================================================
# REMOVE BOARD IMAGE
# ============================================================

@require_POST
def remove_board_image(request, board_id):
    board = get_object_or_404(Board, id=board_id)

    if board.image:
        board.image.delete(save=False)
        board.image = None
        board.save(update_fields=["image"])

    return HttpResponse('<script>location.reload()</script>')



from django.utils import timezone

@require_POST
def delete_attachment(request, card_id):
    card = get_object_or_404(Card, id=card_id)

    # Se não existe anexo, nada a fazer
    if not card.attachment:
        return HttpResponse("No attachment", status=204)

    # REGISTRO NO LOG
    CardLog.objects.create(
        card=card,
        content="Anexo removido",
        attachment=None
    )

    # Apaga o arquivo físico
    card.attachment.delete(save=False)

    # Apaga referência no banco
    card.attachment = None
    card.save(update_fields=["attachment"])

    # Retorna o template do modal atualizado
    return render(request, "boards/partials/card_modal_body.html", {"card": card})


def card_snippet(request, card_id):
    card = get_object_or_404(Card, id=card_id)
    return render(request, "boards/partials/card_item.html", {"card": card})
