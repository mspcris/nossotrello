# boards/views/cards.py

import json
import re

from django.http import HttpResponse, JsonResponse, HttpResponseBadRequest
from django.shortcuts import render, get_object_or_404
from django.views.decorators.http import require_POST, require_http_methods
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.utils import timezone
from django.utils.html import escape

from .helpers import (
    _actor_label,
    _log_card,
    _log_board,
    _save_base64_images_to_media,
    _ensure_attachments_and_activity_for_images,
    _card_modal_context,
    CardForm,
    Board,
    Column,
    Card,
    CardAttachment,
    BoardMembership,
)


def add_card(request, column_id):
    column = get_object_or_404(Column, id=column_id)

    if request.method == "POST":
        form = CardForm(request.POST)
        if not form.is_valid():
            return HttpResponse("Erro ao criar card.", status=400)

        card = form.save(commit=False)
        actor = _actor_label(request)

        raw_desc = (request.POST.get("description") or card.description or "").strip()
        desc_html, saved_paths = _save_base64_images_to_media(raw_desc, folder="quill")
        card.description = desc_html

        card.column = column
        card.position = column.cards.count()
        card.save()

        _log_card(
            card,
            request,
            f"<p><strong>{actor}</strong> criou este card na coluna <strong>{escape(column.name)}</strong>.</p>",
        )

        if saved_paths:
            _ensure_attachments_and_activity_for_images(
                card=card,
                request=request,
                relative_paths=saved_paths,
                actor=actor,
                context_label="descrição",
            )

        # Mantido como estava no seu arquivo original: se existirem essas funções em outro lugar, ok.
        # Se NÃO existirem no projeto, remova esse bloco ou me envie onde elas estão.
        if " _card_has_cover_image" in globals():
            pass

        return render(request, "boards/partials/card_item.html", {"card": card})

    return render(
        request,
        "boards/partials/add_card_form.html",
        {"column": column, "form": CardForm()},
    )


@require_POST
def update_card(request, card_id):
    card = get_object_or_404(Card, id=card_id)

    actor = _actor_label(request)

    old_title = card.title or ""
    old_desc = card.description or ""
    old_tags_raw = card.tags or ""

    card.title = request.POST.get("title", card.title)

    raw_desc = (request.POST.get("description", card.description or "") or "").strip()
    new_desc_html, saved_paths = _save_base64_images_to_media(raw_desc, folder="quill")
    card.description = new_desc_html

    new_tags_raw = request.POST.get("tags", old_tags_raw) or ""

    old_tags = [t.strip() for t in old_tags_raw.split(",") if t.strip()]
    new_tags = [t.strip() for t in new_tags_raw.split(",") if t.strip()]

    card.tags = new_tags_raw
    removed = [t for t in old_tags if t not in new_tags]
    added = [t for t in new_tags if t not in old_tags]

    card.save()

    if saved_paths:
        _ensure_attachments_and_activity_for_images(
            card=card,
            request=request,
            relative_paths=saved_paths,
            actor=actor,
            context_label="descrição",
        )

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

    if not (removed or added or ((old_desc or "").strip() != (card.description or "").strip()) or ((old_title or "").strip() != (card.title or "").strip()) or saved_paths):
        _log_card(card, request, f"<p><strong>{actor}</strong> atualizou o card.</p>")

    return render(request, "boards/partials/card_modal_body.html", _card_modal_context(card))


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
        if request.user.is_staff:
            return True

        memberships_qs = board.memberships.all()
        if memberships_qs.exists():
            return memberships_qs.filter(
                user=request.user,
                role__in=[BoardMembership.Role.OWNER, BoardMembership.Role.EDITOR],
            ).exists()

        return bool(board.created_by_id == request.user.id)

    if not can_move_in_board(old_board) or not can_move_in_board(new_board):
        return JsonResponse({"error": "Sem permissão para mover card neste quadro."}, status=403)

    actor = _actor_label(request)
    old_pos = card.position

    if old_column.id == new_column.id:
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


@login_required
@require_http_methods(["GET"])
def card_move_options(request, card_id):
    card = get_object_or_404(Card, id=card_id, is_deleted=False)
    board_current = card.column.board

    def can_move_in_board(board: Board) -> bool:
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

    if not can_move_in_board(board_current):
        return JsonResponse({"error": "Sem permissão para mover card neste quadro."}, status=403)

    boards = []

    for bm in BoardMembership.objects.filter(
        user=request.user,
        board__is_deleted=False,
    ).select_related("board"):
        boards.append(bm.board)

    legacy_qs = Board.objects.filter(is_deleted=False)
    if not request.user.is_staff:
        legacy_qs = legacy_qs.filter(created_by_id=request.user.id)

    for b in legacy_qs:
        if not b.memberships.exists():
            boards.append(b)

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


def card_modal(request, card_id):
    card = get_object_or_404(Card, id=card_id, is_deleted=False)
    return render(request, "boards/partials/card_modal_body.html", _card_modal_context(card))


def card_snippet(request, card_id):
    card = get_object_or_404(Card, id=card_id)
    return render(request, "boards/partials/card_item.html", {"card": card})


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

@require_POST
def set_tag_color(request, card_id):
    card = get_object_or_404(Card, id=card_id)

    tag = (request.POST.get("tag") or "").strip()
    color = (request.POST.get("color") or "").strip()

    if not tag:
        return HttpResponse("Tag inválida", status=400)

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

    modal_html = render(
        request,
        "boards/partials/card_tags_bar.html",
        {"card": card},
    ).content.decode("utf-8")

    snippet_html = render(
        request,
        "boards/partials/card_item.html",
        {"card": card},
    ).content.decode("utf-8")

    return JsonResponse({
        "modal": modal_html,
        "snippet": snippet_html,
        "card_id": card.id,
    })
