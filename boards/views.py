from django.shortcuts import render, get_object_or_404, redirect
from django.http import HttpResponse, JsonResponse
from django.views.decorators.http import require_POST
from django.db import transaction
from .models import Board, Column, Card
from .forms import ColumnForm, CardForm, BoardForm
import json


def index(request):
    boards = Board.objects.all()
    return render(request, "boards/index.html", {"boards": boards})


def board_detail(request, board_id):
    board = get_object_or_404(Board, id=board_id)
    return render(request, "boards/board_detail.html", {"board": board})


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


def add_card(request, column_id):
    column = get_object_or_404(Column, id=column_id)

    if request.method == "POST":
        form = CardForm(request.POST)
        if form.is_valid():
            card = form.save(commit=False)
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

def edit_card(request, card_id):
    card = get_object_or_404(Card, id=card_id)

    if request.method == "POST":
        card.title = request.POST.get("title", card.title)
        card.save()
        return redirect("board_detail", board_id=card.column.board.id)

    return HttpResponse("Método inválido", status=405)

@require_POST
def update_card(request, card_id):
    card = get_object_or_404(Card, id=card_id)

    if request.method == "POST":
        card.title = request.POST.get("title", "")
        card.description = request.POST.get("description", "")
        card.tags = request.POST.get("tags", "")

        if "attachment" in request.FILES:
            card.attachment = request.FILES["attachment"]

        card.save()

        return render(request, "boards/partials/card_modal_body.html", {"card": card})


def card_modal(request, card_id):
    card = get_object_or_404(Card, id=card_id)
    return render(request, "boards/partials/card_modal_body.html", {"card": card})

def update_card(request, card_id):
    card = get_object_or_404(Card, id=card_id)

    if request.method == "POST":
        card.title = request.POST.get("title", card.title)
        card.description = request.POST.get("description", card.description)
        card.tags = request.POST.get("tags", card.tags)

        # TRATAMENTO DO ARQUIVO
        if "attachment" in request.FILES:
            card.attachment = request.FILES["attachment"]

        card.save()

        return render(
            request,
            "boards/partials/card_modal_body.html",
            {"card": card}
        )

    return HttpResponse("Método inválido", status=405)


@require_POST
@transaction.atomic
def move_card(request):
    data = json.loads(request.body.decode("utf-8"))

    card_id = int(data.get("card_id"))
    new_column_id = int(data.get("new_column_id"))
    new_position = int(data.get("new_position"))

    print("=== MOVE CARD ===")
    print("card_id:", card_id, "new_column_id:", new_column_id, "new_position:", new_position)

    card = get_object_or_404(Card, id=card_id)
    old_column = card.column
    new_column = get_object_or_404(Column, id=new_column_id)

    # 1) Move DENTRO da mesma coluna
    if old_column.id == new_column.id:
        print("-> mesmo coluna")
        cards = list(old_column.cards.order_by("position"))
        cards.remove(card)
        cards.insert(new_position, card)

        for index, c in enumerate(cards):
            if c.position != index:
                c.position = index
                c.save(update_fields=["position"])
        return JsonResponse({"status": "ok"})

    # 2) Move ENTRE colunas
    print("-> coluna diferente")
    # Reordena antiga coluna (sem o card)
    old_cards = list(old_column.cards.exclude(id=card.id).order_by("position"))
    for index, c in enumerate(old_cards):
        if c.position != index:
            c.position = index
            c.save(update_fields=["position"])

    # Atualiza a coluna do card
    card.column = new_column
    card.save(update_fields=["column"])

    # Insere na nova coluna na posição correta
    new_cards = list(new_column.cards.order_by("position"))
    new_cards.insert(new_position, card)

    for index, c in enumerate(new_cards):
        if c.position != index:
            c.position = index
            c.save(update_fields=["position"])

    return JsonResponse({"status": "ok"})


