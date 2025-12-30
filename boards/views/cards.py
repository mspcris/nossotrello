# boards/views/cards.py

import json
import re
import os
import uuid

from django.core.files.base import ContentFile
from django.http import HttpResponse, JsonResponse, HttpResponseBadRequest
from django.shortcuts import render, get_object_or_404
from django.views.decorators.http import require_POST, require_http_methods
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.utils import timezone
from django.utils.html import escape
from django.core.files.uploadedfile import UploadedFile
from django.core.files.storage import default_storage
from django.db.models import F
from django.template.loader import render_to_string

from .helpers import (
    _actor_label,
    _log_card,
    _save_base64_images_to_media,
    _ensure_attachments_and_activity_for_images,
    _card_modal_context,
    _extract_media_image_paths,
    process_mentions_and_notify,
)

# Mantido por compatibilidade com o projeto
from ..permissions import can_edit_board  # noqa: F401

from ..forms import CardForm
from ..models import Board, Column, Card, CardAttachment, BoardMembership


# ============================================================
# PERMISSÕES
# ============================================================
def _user_can_edit_board(user, board: Board) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False

    if getattr(user, "is_staff", False):
        return True

    memberships_qs = getattr(board, "memberships", None)
    if memberships_qs is not None and memberships_qs.exists():
        bm = memberships_qs.filter(user=user).first()
        if not bm:
            return False
        return bm.role in {
            BoardMembership.Role.OWNER,
            BoardMembership.Role.EDITOR,
        }

    return bool(getattr(board, "created_by_id", None) == getattr(user, "id", None))


def _deny_read_only(request, *, as_json: bool = False):
    if as_json:
        return JsonResponse({"error": "Somente leitura."}, status=403)
    return HttpResponse("Somente leitura.", status=403)


# ============================================================
# CARD: CRUD
# ============================================================
@login_required
def add_card(request, column_id):
    column = get_object_or_404(Column, id=column_id)
    board = column.board

    if not _user_can_edit_board(request.user, board):
        return _deny_read_only(request)

    where = (request.GET.get("where") or request.POST.get("where") or "bottom").strip().lower()
    if where not in ("top", "bottom"):
        where = "bottom"

    if request.method == "POST":
        form = CardForm(request.POST)
        if not form.is_valid():
            return HttpResponse("Erro ao criar card.", status=400)

        actor = _actor_label(request)

        with transaction.atomic():
            card = form.save(commit=False)

            raw_desc = (request.POST.get("description") or card.description or "").strip()
            desc_html, saved_paths = _save_base64_images_to_media(raw_desc, folder="quill")
            card.description = desc_html
            card.column = column

            if where == "top":
                Card.objects.filter(column=column).update(position=F("position") + 1)
                card.position = 0
            else:
                card.position = column.cards.count()

            card.save()

            board = card.column.board
            board.version += 1
            board.save(update_fields=["version"])

            try:
                process_mentions_and_notify(
                    request=request,
                    board=board,
                    card=card,
                    source="description",
                    raw_text=raw_desc,
                )
            except Exception:
                pass

            _log_card(
                card,
                request,
                (
                    f"<p><strong>{actor}</strong> criou este card na coluna "
                    f"<strong>{escape(column.name)}</strong>.</p>"
                ),
            )

        referenced_paths = _extract_media_image_paths(card.description or "", folder="quill")
        all_paths = list(dict.fromkeys((saved_paths or []) + (referenced_paths or [])))

        if all_paths:
            _ensure_attachments_and_activity_for_images(
                card=card,
                request=request,
                relative_paths=all_paths,
                actor=actor,
                context_label="descrição",
            )

        return render(request, "boards/partials/card_item.html", {"card": card})

    return render(
        request,
        "boards/partials/add_card_form.html",
        {"column": column, "form": CardForm(), "where": where},
    )

@login_required
@require_POST
def update_card(request, card_id):
    card = get_object_or_404(Card, id=card_id)
    actor = _actor_label(request)

    # ✅ Escrita: bloqueio forte para VIEWER
    if not _user_can_edit_board(request.user, card.column.board):
        return _deny_read_only(request, as_json=True)

    old_title = card.title or ""
    old_desc = card.description or ""
    old_tags_raw = card.tags or ""

    card.title = request.POST.get("title", card.title)

    raw_desc = (request.POST.get("description", card.description or "") or "").strip()
    new_desc_html, saved_paths = _save_base64_images_to_media(raw_desc, folder="quill")
    card.description = new_desc_html

    new_tags_raw = request.POST.get("tags", old_tags_raw) or ""

    old_tags = [t.strip() for t in (old_tags_raw or "").split(",") if t.strip()]
    new_tags = [t.strip() for t in (new_tags_raw or "").split(",") if t.strip()]

    card.tags = new_tags_raw
    removed = [t for t in old_tags if t not in new_tags]
    added = [t for t in new_tags if t not in old_tags]

    card.save()
    board = card.column.board
    board.version += 1
    board.save(update_fields=["version"])

    # ✅ menções na descrição (texto bruto do POST)
    import logging
    logger = logging.getLogger(__name__)
    try:
        process_mentions_and_notify(
            request=request,
            board=card.column.board,
            card=card,
            source="description",
            raw_text=raw_desc,
        )
    except Exception:
        logger.exception("Erro ao processar menções na atualização de card.")

    # Garante anexos + atividade para imagens (base64 e/ou já persistidas em /media/)
    referenced_paths = _extract_media_image_paths(card.description or "", folder="quill")
    all_paths = list(dict.fromkeys((saved_paths or []) + (referenced_paths or [])))

    if all_paths:
        _ensure_attachments_and_activity_for_images(
            card=card,
            request=request,
            relative_paths=all_paths,
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

    if not (
        removed
        or added
        or ((old_desc or "").strip() != (card.description or "").strip())
        or ((old_title or "").strip() != (card.title or "").strip())
        or all_paths
    ):
        _log_card(card, request, f"<p><strong>{actor}</strong> atualizou o card.</p>")

    return render(request, "boards/partials/card_modal_body.html", _card_modal_context(card))


@login_required
def edit_card(request, card_id):
    """
    Modal antigo.
    Também é ESCRITA (salva via form), então precisa respeitar somente leitura.
    """
    card = get_object_or_404(Card, id=card_id)

    if not _user_can_edit_board(request.user, card.column.board):
        return _deny_read_only(request)

    if request.method == "POST":
        form = CardForm(request.POST, request.FILES, instance=card)
        if form.is_valid():
            form.save()

            actor = _actor_label(request)
            _log_card(card, request, f"<p><strong>{actor}</strong> editou o card (modal antigo).</p>")

            return render(request, "boards/partials/card_modal_body.html", _card_modal_context(card))
    else:
        form = CardForm(instance=card)

    return render(request, "boards/partials/card_edit_form.html", {"card": card, "form": form})


@login_required
@require_POST
def delete_card(request, card_id):
    card = get_object_or_404(Card.all_objects, id=card_id)
    actor = _actor_label(request)

    # ✅ Escrita: bloquear VIEWER
    if not _user_can_edit_board(request.user, card.column.board):
        return _deny_read_only(request)

    if not card.is_deleted:
        _log_card(card, request, f"<p><strong>{actor}</strong> excluiu (soft delete) este card.</p>")
        card.is_deleted = True
        card.deleted_at = timezone.now()
        card.save(update_fields=["is_deleted", "deleted_at"])
        board = card.column.board
        board.version += 1
        board.save(update_fields=["version"])
    return HttpResponse("", status=200)


@login_required
@require_POST
@transaction.atomic
def move_card(request):
    """
    Move um card dentro da mesma coluna ou entre colunas.
    Implementação determinística para evitar rollback visual via polling.
    """
    data = json.loads(request.body.decode("utf-8"))

    card_id = int(data.get("card_id"))
    new_column_id = int(data.get("new_column_id"))
    new_position = int(data.get("new_position"))

    card = get_object_or_404(Card, id=card_id)

    old_column = card.column
    new_column = get_object_or_404(Column, id=new_column_id)

    old_board = old_column.board
    new_board = new_column.board

    # permissão (origem e destino)
    if (
        not _user_can_edit_board(request.user, old_board)
        or not _user_can_edit_board(request.user, new_board)
    ):
        return _deny_read_only(request, as_json=True)

    actor = _actor_label(request)
    old_pos = int(card.position or 0)

    # ============================================================
    # 1) MOVER DENTRO DA MESMA COLUNA (CORRIGIDO)
    # ============================================================
    if old_column.id == new_column.id:
        # cards exceto o movido
        siblings = list(
            old_column.cards
            .exclude(id=card.id)
            .order_by("position")
        )

        # clamp
        if new_position < 0:
            new_position = 0
        if new_position > len(siblings):
            new_position = len(siblings)

        # reindexa os outros cards
        for index, c in enumerate(siblings):
            if index >= new_position:
                c.position = index + 1
            else:
                c.position = index
            c.save(update_fields=["position"])

        # salva o card movido isoladamente
        card.position = new_position
        card.save(update_fields=["position"])

        # versão do board
        old_board.version += 1
        old_board.save(update_fields=["version"])

        _log_card(
            card,
            request,
            (
                f"<p><strong>{actor}</strong> reordenou este card dentro da coluna "
                f"<strong>{escape(old_column.name)}</strong> "
                f"(de {old_pos} para {new_position}).</p>"
            ),
        )

        return JsonResponse({"status": "ok"})

    # ============================================================
    # 2) MOVER PARA OUTRA COLUNA (ESTÁVEL)
    # ============================================================

    # reindexa coluna antiga
    old_cards = list(
        old_column.cards
        .exclude(id=card.id)
        .order_by("position")
    )

    for index, c in enumerate(old_cards):
        if int(c.position or 0) != index:
            c.position = index
            c.save(update_fields=["position"])

    # move card para nova coluna
    card.column = new_column
    card.save(update_fields=["column"])

    # cards da nova coluna (sem o card)
    new_cards = list(
        new_column.cards
        .exclude(id=card.id)
        .order_by("position")
    )

    # clamp
    if new_position < 0:
        new_position = 0
    if new_position > len(new_cards):
        new_position = len(new_cards)

    # reindexa nova coluna
    for index, c in enumerate(new_cards):
        if index >= new_position:
            c.position = index + 1
        else:
            c.position = index
        c.save(update_fields=["position"])

    # posiciona o card
    card.position = new_position
    card.save(update_fields=["position"])

    # versão do board destino
    new_board.version += 1
    new_board.save(update_fields=["version"])

    _log_card(
        card,
        request,
        (
            f"<p><strong>{actor}</strong> moveu este card de "
            f"<strong>{escape(old_column.name)}</strong> para "
            f"<strong>{escape(new_column.name)}</strong>.</p>"
        ),
    )

    return JsonResponse({"status": "ok"})





@login_required
@require_http_methods(["GET"])
def card_move_options(request, card_id):
    """
    Tela/opções de mover é ESCRITA (porque habilita operação de mover).
    Então VIEWER não deve nem carregar isso.
    """
    card = get_object_or_404(Card, id=card_id, is_deleted=False)
    board_current = card.column.board

    if not _user_can_edit_board(request.user, board_current):
        return _deny_read_only(request)

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
            {"id": c.id, "name": c.name, "positions_total_plus_one": (c.cards.count() + 1)}
            for c in cols
        ]

    payload = {
        "current": {
            "board_id": board_current.id,
            "board_name": board_current.name,
            "column_id": card.column.id,
            "column_name": card.column.name,
            "position": int(card.position or 0),         # 0-based (para o select)
            "position_display": int(card.position or 0) + 1,  # 1-based (para mostrar na UI)
        },
        "boards": [{"id": b.id, "name": b.name} for b in uniq],
        "columns_by_board": columns_by_board,
    }
    return JsonResponse(payload)


def card_modal(request, card_id):
    # ✅ leitura do modal é permitida (somente leitura continua vendo)
    card = get_object_or_404(Card, id=card_id, is_deleted=False)
    return render(request, "boards/partials/card_modal_body.html", _card_modal_context(card))


def card_snippet(request, card_id):
    # ✅ snippet é leitura
    card = get_object_or_404(Card, id=card_id)
    return render(request, "boards/partials/card_item.html", {"card": card})




# ============================================================
# DUPLICAR CARD
# ============================================================
@login_required
@require_POST
@transaction.atomic
def duplicate_card(request, card_id):
    card = get_object_or_404(Card, id=card_id, is_deleted=False)
    column = card.column
    board = column.board

    # ✅ Escrita: bloquear VIEWER
    if not _user_can_edit_board(request.user, board):
        return JsonResponse({"error": "Somente leitura."}, status=403)

    actor = _actor_label(request)

    # posição: duplicata entra logo abaixo do card atual
    new_position = int(card.position or 0) + 1

    # empurra pra baixo quem está >= new_position
    Card.objects.filter(
        column=column,
        is_deleted=False,
        position__gte=new_position,
    ).update(position=F("position") + 1)

    # cria a cópia (mantém campos importantes)
    base_title = (card.title or "").strip()

    # evita duplicar sufixo
    if base_title.endswith("(Novo)") or base_title.endswith("+ (Novo)"):
        new_title = base_title
    else:
        new_title = f"{base_title} + (Novo)" if base_title else "(Novo)"

    new_card = Card.objects.create(
        column=column,
        position=new_position,
        title=new_title,
        description=(card.description or ""),
        tags=(card.tags or ""),
        tag_colors=(card.tag_colors or ""),
        cover_image=card.cover_image,
    )

    # copia anexos (referenciam os mesmos arquivos)
    try:
        atts = list(card.attachments.all())
        if atts:
            CardAttachment.objects.bulk_create(
                [
                    CardAttachment(
                        card=new_card,
                        file=a.file,
                        description=(a.description or ""),
                    )
                    for a in atts
                ]
            )
    except Exception:
        # anexos não podem derrubar o fluxo
        pass

    _log_card(
        new_card,
        request,
        (
            f"<p><strong>{actor}</strong> duplicou este card a partir de "
            f"<strong>{escape(card.title or 'sem título')}</strong>.</p>"
        ),
    )

    # devolve snippet pronto pro front inserir no DOM
    snippet_html = render_to_string(
        "boards/partials/card_item.html",
        {"card": new_card},
        request=request,
    )

    return JsonResponse(
        {
            "status": "ok",
            "card_id": new_card.id,
            "column_id": column.id,
            "position": int(new_position),
            "snippet": snippet_html,
        }
    )




# ============================================================
# TAGS
# ============================================================
@login_required
@require_POST
def remove_tag(request, card_id):
    card = get_object_or_404(Card, id=card_id)
    actor = _actor_label(request)

    # ✅ Escrita: bloquear VIEWER
    if not _user_can_edit_board(request.user, card.column.board):
        return _deny_read_only(request, as_json=True)

    tag = request.POST.get("tag", "").strip()
    if not tag:
        return HttpResponse("Tag inválida", status=400)

    old_tags = [t.strip() for t in (card.tags or "").split(",") if t.strip()]
    new_tags = [t for t in old_tags if t != tag]

    if len(old_tags) == len(new_tags):
        return HttpResponse("Tag não encontrada", status=404)

    card.tags = ", ".join(new_tags)
    card.save(update_fields=["tags"])
    board = card.column.board
    board.version += 1
    board.save(update_fields=["version"])
    _log_card(card, request, f"<p><strong>{actor}</strong> removeu a etiqueta <strong>{escape(tag)}</strong>.</p>")

    modal_html = render(request, "boards/partials/card_modal_body.html", _card_modal_context(card)).content.decode("utf-8")
    snippet_html = render(request, "boards/partials/card_item.html", {"card": card}).content.decode("utf-8")

    return JsonResponse({"modal": modal_html, "snippet": snippet_html, "card_id": card.id})


@login_required
@require_POST
def set_tag_color(request, card_id):
    card = get_object_or_404(Card, id=card_id)

    # ✅ Escrita: bloquear VIEWER
    if not _user_can_edit_board(request.user, card.column.board):
        return _deny_read_only(request, as_json=True)

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
    board = card.column.board
    board.version += 1
    board.save(update_fields=["version"])
    tags_bar = render_to_string(
        "boards/partials/card_tags_bar.html",
        {"card": card},
        request=request,
    )

    snippet_html = render_to_string(
        "boards/partials/card_item.html",
        {"card": card},
        request=request,
    )

    return JsonResponse(
        {
            "ok": True,
            "tags_bar": tags_bar,
            "card_id": card.id,
            "snippet": snippet_html,
        }
    )































# ============================================================
# CAPA DO CARD (modal)
# - garante que a capa também vira anexo e aparece na atividade com thumbnail/link
# ============================================================
@login_required
@require_POST
def set_card_cover(request, card_id):
    """
    Define/atualiza a capa do card.

    Regra do histórico (anti-404):
      - se havia capa anterior, COPIA fisicamente o arquivo antigo para attachments/
        e registra esse arquivo como "Capa do card (anterior)".
      - depois atualiza cover_image normalmente.
      - registra a capa atual (new_rel) como "Capa do card".
    """
    card = get_object_or_404(Card, id=card_id, is_deleted=False)
    actor = _actor_label(request)

    # ✅ Escrita: bloquear VIEWER
    if not _user_can_edit_board(request.user, card.column.board):
        return _deny_read_only(request)

    f: UploadedFile | None = request.FILES.get("cover")
    if not f:
        return HttpResponseBadRequest("Envie uma imagem no campo 'cover'.")

    ctype = (getattr(f, "content_type", "") or "").lower()
    if not ctype.startswith("image/"):
        return HttpResponseBadRequest("Arquivo inválido: envie uma imagem.")

    max_bytes = 15 * 1024 * 1024  # 15MB
    if getattr(f, "size", 0) and f.size > max_bytes:
        return HttpResponseBadRequest("Imagem muito grande. Tente uma menor (até 15MB).")

    # ============================================================
    # 1) Captura a capa anterior (RELATIVA) e copia para attachments/
    # ============================================================
    old_rel = ""
    old_hist_rel = ""  # <-- cópia física em attachments/ (é isso que vai pro histórico)
    try:
        if getattr(card, "cover_image", None) and card.cover_image:
            old_rel = (card.cover_image.name or "").strip()  # ex: card_covers/old.png
    except Exception:
        old_rel = ""

    if old_rel:
        try:
            # tenta preservar extensão
            ext = os.path.splitext(old_rel)[1].lower()  # ".png"
            if not ext:
                ext = ".png"

            # caminho novo imutável dentro de attachments/
            old_hist_rel = f"attachments/cover_history/{uuid.uuid4().hex}{ext}"

            # lê bytes do storage e salva a cópia
            with default_storage.open(old_rel, "rb") as fp:
                data = fp.read()

            if data:
                default_storage.save(old_hist_rel, ContentFile(data))
            else:
                old_hist_rel = ""  # sem bytes => não registra
        except Exception:
            old_hist_rel = ""  # se falhar a cópia, não quebra o fluxo

    # ============================================================
    # 2) Atualiza a capa (isso pode disparar cleanup do arquivo antigo)
    # ============================================================
    card.cover_image = f
    card.save(update_fields=["cover_image"])
    board = card.column.board
    board.version += 1
    board.save(update_fields=["version"])
    # pega rel da nova
    new_rel = ""
    try:
        if getattr(card, "cover_image", None) and card.cover_image:
            new_rel = (card.cover_image.name or "").strip()
    except Exception:
        new_rel = ""

    # ============================================================
    # 3) Garante attachments (histórico usa a CÓPIA, não o old_rel)
    # ============================================================
    try:
        if old_hist_rel and not card.attachments.filter(file=old_hist_rel).exists():
            CardAttachment.objects.create(
                card=card,
                file=old_hist_rel,
                description="Capa do card (anterior)",
            )
    except Exception:
        pass

    try:
        if new_rel and not card.attachments.filter(file=new_rel).exists():
            CardAttachment.objects.create(
                card=card,
                file=new_rel,
                description="Capa do card",
            )
    except Exception:
        pass

    # ============================================================
    # 4) Log com thumbnail + link (histórico aponta para old_hist_rel)
    # ============================================================
    try:
        parts = [f"<p><strong>{actor}</strong> definiu/atualizou a capa do card.</p>"]

        # ✅ PRIMEIRO: capa atual
        if new_rel:
            new_url = default_storage.url(new_rel)
            new_name = escape(new_rel.split("/")[-1])
            parts.append(
                "<div style='margin:8px 0'>"
                "<div><em>Capa atual:</em> "
                f"<a href='{escape(new_url)}' target='_blank' rel='noopener'>{new_name}</a></div>"
                f"<div style='margin-top:6px'><img src='{escape(new_url)}' style='max-width:100%; border-radius:8px'/></div>"
                "</div>"
            )

        # ✅ DEPOIS: capa anterior (anti-404)
        # Preferência: usar a cópia imutável em attachments/cover_history (old_hist_rel)
        # Fallback: usar o caminho antigo original (old_rel) se a cópia falhar
        old_log_rel = (old_hist_rel or old_rel or "").strip()
        if old_log_rel:
            old_url = default_storage.url(old_log_rel)
            old_name = escape(old_log_rel.split("/")[-1])
            parts.append(
                "<div style='margin:8px 0'>"
                "<div><em>Capa anterior:</em> "
                f"<a href='{escape(old_url)}' target='_blank' rel='noopener'>{old_name}</a></div>"
                f"<div style='margin-top:6px'><img src='{escape(old_url)}' style='max-width:100%; border-radius:8px'/></div>"
                "</div>"
            )

        _log_card(card, request, "".join(parts))
    except Exception:
        pass

    return render(request, "boards/partials/card_modal_body.html", _card_modal_context(card))


@login_required
@require_POST
def remove_card_cover(request, card_id):
    """
    Remove a capa do card (só desassocia do card).
    NÃO apaga arquivo físico automaticamente (usuário apaga via Anexos).
    """
    card = get_object_or_404(Card, id=card_id, is_deleted=False)
    actor = _actor_label(request)

    # ✅ Escrita: bloquear VIEWER
    if not _user_can_edit_board(request.user, card.column.board):
        return _deny_read_only(request)

    # guarda a rel atual para log
    old_rel = ""
    try:
        if getattr(card, "cover_image", None) and card.cover_image:
            old_rel = (card.cover_image.name or "").strip()
    except Exception:
        old_rel = ""

    # só zera o campo (sem deletar arquivo)
    card.cover_image = None
    card.save(update_fields=["cover_image"])
    board = card.column.board
    board.version += 1
    board.save(update_fields=["version"])
    try:
        if old_rel:
            old_url = default_storage.url(old_rel)
            old_name = escape(old_rel.split("/")[-1])
            _log_card(
                card,
                request,
                (
                    f"<p><strong>{actor}</strong> removeu a capa do card.</p>"
                    "<div style='margin:8px 0'>"
                    "<div><em>Capa removida:</em> "
                    f"<a href='{escape(old_url)}' target='_blank' rel='noopener'>{old_name}</a></div>"
                    f"<div style='margin-top:6px'><img src='{escape(old_url)}' style='max-width:100%; border-radius:8px'/></div>"
                    "</div>"
                ),
            )
        else:
            _log_card(card, request, f"<p><strong>{actor}</strong> removeu a capa do card.</p>")
    except Exception:
        pass

    return render(request, "boards/partials/card_modal_body.html", _card_modal_context(card))
# end file boards/views/cards.py
