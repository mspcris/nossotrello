# boards/views/cards.py

from asyncio.log import logger
import json
import os
import re
import uuid
import logging


from datetime import datetime
from datetime import date as _date

from django.contrib.auth.decorators import login_required
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import UploadedFile
from django.db import transaction
from django.db.models import F
from django.http import HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.html import escape
from django.views.decorators.http import require_POST, require_http_methods

from .helpers import (
    _actor_label,
    _card_modal_context,
    _ensure_attachments_and_activity_for_images,
    _extract_media_image_paths,
    _log_card,
    _save_base64_images_to_media,
    process_mentions_and_notify,
)

# Mantido por compatibilidade com o projeto
from ..permissions import can_edit_board  # noqa: F401

from ..forms import CardForm
from ..models import Board, BoardMembership, Card, CardAttachment, Column, CardSeen
# regra: se due_date preenchida => warn obrigatória
from datetime import timedelta
from django.utils.html import strip_tags


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
def _parse_any_date(s: str):
    """
    Aceita:
      - YYYY-MM-DD (input type=date)
      - DD/MM/YYYY (campo texto)
    Retorna datetime.date ou None.
    """
    raw = (s or "").strip()
    if not raw:
        return None

    d = parse_date(raw)
    if d:
        return d

    # fallback BR
    try:
        return datetime.strptime(raw, "%d/%m/%Y").date()
    except Exception:
        return None







from datetime import date as _date, timedelta
import logging
import re

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils.html import escape
from django.views.decorators.http import require_POST


def _fmt_date_br(d):
    try:
        return d.strftime("%d/%m/%Y") if d else "—"
    except Exception:
        return "—"


def _fmt_bool(v):
    return "Sim" if bool(v) else "Não"




























@login_required
@require_POST
def update_card(request, card_id):
    """
    Arquivo: boards/views/cards.py
    Substituir a função inteira.

    O que esta versão garante:
    - Loga na Atividade quando mudar TÍTULO
    - Loga na Atividade quando mudar DESCRIÇÃO (com resumo Antes/Depois)
    - Mantém seus logs atuais de prazo / data início / etc.
    - Fallback só quando realmente nada relevante mudou
    """
    from django.utils.html import strip_tags
    from django.utils.html import escape

    def _summarize_html(html: str, limit: int = 220) -> str:
        txt = strip_tags(html or "").strip()
        if len(txt) > limit:
            return txt[:limit].rstrip() + "…"
        return txt

    def _norm(s: str) -> str:
        return (s or "").strip()

    card = get_object_or_404(Card, id=card_id)
    actor = _actor_label(request)
    board = card.column.board

    # ✅ Escrita: bloqueio forte para VIEWER
    if not _user_can_edit_board(request.user, board):
        return _deny_read_only(request, as_json=True)

    # ============================================================
    # SNAPSHOT (antes)
    # ============================================================
    old_title = _norm(card.title)
    old_desc = _norm(card.description)
    old_tags_raw = card.tags or ""

    old_start_date = card.start_date
    old_due_date = card.due_date
    old_due_warn_date = card.due_warn_date
    old_due_notify = bool(card.due_notify)

    # ============================================================
    # UPDATE: logging inicial
    # ============================================================
    posted_title = request.POST.get("title", None)
    posted_titles = request.POST.getlist("title")
    logger.warning(
        "[update_card] card_id=%s keys=%s title(get)=%r titles(getlist)=%r",
        card_id,
        sorted(list(request.POST.keys())),
        posted_title,
        posted_titles,
    )


    # ============================================================
    # UPDATE: título / descrição / tags
    # ============================================================
    # pega TODOS os "title" enviados (evita ambiguidade com checklist)
    titles = [(_norm(x)) for x in request.POST.getlist("title") if _norm(x)]

    # prioridade: aliases > primeiro title não-vazio > mantém o atual
    posted_title = _norm(request.POST.get("card_title") or request.POST.get("cm_title") or "")
    new_title = posted_title or (titles[0] if titles else old_title)

    card.title = new_title


    raw_desc = _norm(request.POST.get("description", card.description or ""))
    new_desc_html, saved_paths = _save_base64_images_to_media(raw_desc, folder="quill")
    card.description = _norm(new_desc_html)

    new_tags_raw = request.POST.get("tags", old_tags_raw) or ""

    # ============================================================
    # PRAZOS (inclui DATA DE INÍCIO)
    # ============================================================
    start_date_raw = (request.POST.get("start_date") or "").strip()
    due_date_raw = (request.POST.get("due_date") or "").strip()
    due_warn_raw = (request.POST.get("due_warn_date") or "").strip()
    due_notify_raw = (request.POST.get("due_notify") or "").strip()

    start_date = _parse_any_date(start_date_raw)
    due_date = _parse_any_date(due_date_raw)
    due_warn_date = _parse_any_date(due_warn_raw)

    if due_notify_raw:
        due_notify = str(due_notify_raw).strip().lower() in ("1", "true", "on", "yes")
    else:
        due_notify = True

    # regra: se due_date preenchida e warn vazio => default = due-5
    if due_date and not due_warn_date:
        due_warn_date = due_date - timedelta(days=5)

    card.start_date = start_date
    card.due_date = due_date
    card.due_warn_date = due_warn_date
    card.due_notify = bool(due_notify)

    # ============================================================
    # TAGS: diff
    # ============================================================
    old_tags = [t.strip() for t in (old_tags_raw or "").split(",") if t.strip()]
    new_tags = [t.strip() for t in (new_tags_raw or "").split(",") if t.strip()]

    card.tags = new_tags_raw
    removed = [t for t in old_tags if t not in new_tags]
    added = [t for t in new_tags if t not in old_tags]

    # ============================================================
    # SAVE CARD
    # ============================================================
    card.save()
    card.refresh_from_db(fields=["title", "description", "tags", "start_date", "due_date", "due_warn_date", "due_notify"])

    # ============================================================
    # DIFFS pós-save
    # ============================================================
    title_changed = (old_title != _norm(card.title))
    desc_changed = (old_desc != _norm(card.description))

    start_date_changed = (old_start_date != card.start_date)
    due_date_changed = (old_due_date != card.due_date)
    due_warn_changed = (old_due_warn_date != card.due_warn_date)
    due_notify_changed = (old_due_notify != bool(card.due_notify))

    # ============================================================
    # LOG — TÍTULO
    # ============================================================
    if title_changed:
        _log_card(
            card,
            request,
            (
                f"<p><strong>{actor}</strong> alterou o título.</p>"
                "<ul style='margin:6px 0 0 18px;'>"
                "<li><strong>Título:</strong> "
                f"{escape(old_title)} → "
                f"<strong>{escape(_norm(card.title))}</strong></li>"
                "</ul>"
            ),
        )

    # ============================================================
    # LOG — DESCRIÇÃO
    # (Resumo do conteúdo; evita jogar HTML gigante no log)
    # ============================================================
    if desc_changed:
        before = escape(_summarize_html(old_desc))
        after = escape(_summarize_html(card.description))

        _log_card(
            card,
            request,
            (
                f"<p><strong>{actor}</strong> alterou a descrição.</p>"
                "<div style='margin-top:6px'>"
                "<div style='font-size:12px;opacity:.75;margin-bottom:4px'>Antes:</div>"
                f"<div style='padding:10px;border:1px solid rgba(15,23,42,0.10);"
                "border-radius:10px;background:rgba(255,255,255,0.35)'>"
                f"<em>{before}</em></div>"
                "</div>"
                "<div style='margin-top:10px'>"
                "<div style='font-size:12px;opacity:.75;margin-bottom:4px'>Depois:</div>"
                f"<div style='padding:10px;border:1px solid rgba(15,23,42,0.10);"
                "border-radius:10px;background:rgba(255,255,255,0.35)'>"
                f"<strong>{after}</strong></div>"
                "</div>"
            ),
        )

        # ============================================================
        # MENÇÕES — DESCRIÇÃO (Escolha A)
        # Notifica usuários mencionados na edição da descrição
        # ============================================================
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




    # ============================================================
    # LOG — PRAZO
    # ============================================================
    if due_date_changed or due_warn_changed or due_notify_changed:
        parts = [
            f"<p><strong>{actor}</strong> alterou o prazo do card.</p>",
            "<ul style='margin:6px 0 0 18px;'>",
        ]

        if due_date_changed:
            parts.append(
                "<li><strong>Vencimento:</strong> "
                f"{escape(_fmt_date_br(old_due_date))} → "
                f"<strong>{escape(_fmt_date_br(card.due_date))}</strong></li>"
            )

        if due_warn_changed:
            parts.append(
                "<li><strong>Avisar em:</strong> "
                f"{escape(_fmt_date_br(old_due_warn_date))} → "
                f"<strong>{escape(_fmt_date_br(card.due_warn_date))}</strong></li>"
            )

        if due_notify_changed:
            parts.append(
                "<li><strong>Notificar com cores:</strong> "
                f"{escape(_fmt_bool(old_due_notify))} → "
                f"<strong>{escape(_fmt_bool(card.due_notify))}</strong></li>"
            )

        parts.append("</ul>")
        _log_card(card, request, "".join(parts))

    # ============================================================
    # LOG — DATA DE INÍCIO (independente)
    # ============================================================
    if start_date_changed:
        _log_card(
            card,
            request,
            (
                f"<p><strong>{actor}</strong> alterou a data de início.</p>"
                "<ul style='margin:6px 0 0 18px;'>"
                "<li><strong>Data de início:</strong> "
                f"{escape(_fmt_date_br(old_start_date))} → "
                f"<strong>{escape(_fmt_date_br(card.start_date))}</strong></li>"
                "</ul>"
            ),
        )

    # ============================================================
    # CORES do board (badge de prazo)
    # ============================================================
    if any(k in request.POST for k in ("due_color_ok", "due_color_warn", "due_color_overdue")):
        posted_ok = (request.POST.get("due_color_ok") or "").strip()
        posted_warn = (request.POST.get("due_color_warn") or "").strip()
        posted_over = (request.POST.get("due_color_overdue") or "").strip()

        current = getattr(board, "due_colors", None) or {}
        if not isinstance(current, dict):
            current = {}

        new_ok = posted_ok or (current.get("ok") or "")
        new_warn = posted_warn or (current.get("warn") or "")
        new_over = posted_over or (current.get("overdue") or "")

        def valid_hex(c: str) -> bool:
            return bool(re.match(r"^#[0-9a-fA-F]{6}$", c or ""))

        if new_ok and new_warn and new_over and all(valid_hex(c) for c in (new_ok, new_warn, new_over)):
            board.due_colors = {"ok": new_ok, "warn": new_warn, "overdue": new_over}
            board.save(update_fields=["due_colors"])
        else:
            return JsonResponse({"error": "Cores inválidas/incompletas."}, status=400)

    # ============================================================
    # VERSION
    # ============================================================
    board.version += 1
    board.save(update_fields=["version"])

    # ============================================================
    # FALLBACK (só se nada relevante mudou)
    # ============================================================
    if not (
        removed
        or added
        or title_changed
        or desc_changed
        or start_date_changed
        or due_date_changed
        or due_warn_changed
        or due_notify_changed
        or saved_paths
    ):
        _log_card(card, request, f"<p><strong>{actor}</strong> atualizou o card.</p>")

    ctx = _card_modal_context(card)
    ctx["board_due_colors"] = getattr(board, "due_colors", {}) or {}
    return _render_card_modal(request, card, ctx)




























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

            return _render_card_modal(request, card)
    else:
        form = CardForm(instance=card)

    return _render_card_modal(request, card)



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
def archive_card(request, card_id):
    card = get_object_or_404(Card, id=card_id, is_deleted=False)
    actor = _actor_label(request)

    if not _user_can_edit_board(request.user, card.column.board):
        return _deny_read_only(request)

    if not getattr(card, "is_archived", False):
        _log_card(card, request, f"<p><strong>{actor}</strong> arquivou este card.</p>")
        card.is_archived = True
        card.archived_at = timezone.now()
        card.save(update_fields=["is_archived", "archived_at"])

        board = card.column.board
        board.version += 1
        board.save(update_fields=["version"])

    return HttpResponse("", status=200)


@login_required
@require_POST
def unarchive_card(request, card_id):
    card = get_object_or_404(Card, id=card_id, is_deleted=False)
    actor = _actor_label(request)

    if not _user_can_edit_board(request.user, card.column.board):
        return _deny_read_only(request)

    if getattr(card, "is_archived", False):
        _log_card(card, request, f"<p><strong>{actor}</strong> desarquivou este card.</p>")
        card.is_archived = False
        card.archived_at = None
        card.save(update_fields=["is_archived", "archived_at"])

        board = card.column.board
        board.version += 1
        board.save(update_fields=["version"])

    return HttpResponse("", status=200)


@login_required
@require_POST
@transaction.atomic
def restore_card(request, card_id):
    # restaura da lixeira (soft delete -> ativo)
    card = get_object_or_404(Card.all_objects, id=card_id)
    actor = _actor_label(request)

    if not _user_can_edit_board(request.user, card.column.board):
        return _deny_read_only(request)

    if card.is_deleted:
        # volta ativo e fora do arquivo
        card.is_deleted = False
        card.deleted_at = None
        card.is_archived = False
        card.archived_at = None

        # coloca no fim da coluna (entre ativos não-arquivados)
        from django.db.models import Max
        last_pos = (
            Card.objects
            .filter(column=card.column, is_archived=False)
            .aggregate(m=Max("position"))
            .get("m")
        )
        card.position = int(last_pos or 0) + 1

        card.save(update_fields=[
            "is_deleted", "deleted_at",
            "is_archived", "archived_at",
            "position",
        ])

        _log_card(card, request, f"<p><strong>{actor}</strong> restaurou este card da lixeira.</p>")

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





def _render_card_modal(request, card, context=None):
    ctx = context or _card_modal_context(card)

    # ✅ CHECKLISTS (total/done calculados no backend)
    from django.db.models import Count, Q  # pode mover pro topo depois

    checklists = (
        card.checklists
            .all()
            # .annotate(
                # total=Count("items", distinct=True),
                # done=Count("items", filter=Q(items__checked=True), distinct=True),
            # )
    )
    ctx["checklists"] = checklists

    # hardening: garante chaves usadas nos templates
    ctx.setdefault("card", card)
    ctx.setdefault("column", getattr(card, "column", None))
    ctx.setdefault("board", getattr(getattr(card, "column", None), "board", None))
    # ⚠️ REMOVER esta linha, senão você sobrescreve o annotate:
    # ctx.setdefault("checklists", card.checklists.all())
    ctx.setdefault("board_due_colors", (getattr(card.column.board, "due_colors", None) or {}))

    profile = getattr(request.user, "profile", None)
    use_sidebar = bool(profile and getattr(profile, "activity_sidebar", False))

    template_name = (
        "boards/partials/card_modal_split.html"
        if use_sidebar
        else "boards/partials/card_modal_body.html"
    )

    return render(request, template_name, ctx)


def _summarize_html(html: str, limit: int = 220) -> str:
    txt = strip_tags(html or "")
    txt = re.sub(r"\s+", " ", txt).strip()
    if not txt:
        return "(vazio)"
    if len(txt) <= limit:
        return txt
    return txt[:limit].rstrip() + "…"




@login_required
def card_modal(request, card_id):
    card = get_object_or_404(Card, id=card_id, is_deleted=False)

    # ============================================================
    # READ MARK — marca o card como visto pelo usuário
    # ============================================================
    CardSeen.objects.update_or_create(
        card=card,
        user=request.user,
        defaults={"last_seen_at": timezone.now()},
    )

    # ✅ LOGS ORDENADOS (mais novos primeiro)
    logs = card.logs.order_by("-created_at")

    ctx = _card_modal_context(card)
    ctx["logs"] = logs

    return _render_card_modal(request, card, ctx)





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

    modal_html = _render_card_modal(request, card, _card_modal_context(card)).content.decode("utf-8")
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

    return _render_card_modal(request, card)


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

    return _render_card_modal(request, card)



@login_required
def card_snippet(request, card_id):
    card = get_object_or_404(Card, id=card_id, is_deleted=False)
    return render(request, "boards/partials/card_item.html", {"card": card})




@login_required
@require_POST
@transaction.atomic
def reorder_cards_in_column(request, column_id: int):
    """Persiste a ordem dos cards da coluna (position 0..N-1)."""
    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return HttpResponseBadRequest("JSON inválido.")

    ordered_ids = data.get("ordered_card_ids")
    if not isinstance(ordered_ids, list):
        return HttpResponseBadRequest("ordered_card_ids deve ser uma lista.")

    column = get_object_or_404(Column, id=column_id)
    board = column.board

    # Escrita: bloquear somente leitura (mesma linha do move_card/ações JS)
    if not _user_can_edit_board(request.user, board):
        return _deny_read_only(request, as_json=True)  # 403 JSON "Somente leitura." :contentReference[oaicite:2]{index=2}

    # Normaliza ids e valida pertencimento à coluna
    try:
        normalized = [int(x) for x in ordered_ids]
    except Exception:
        return HttpResponseBadRequest("IDs inválidos em ordered_card_ids.")

    cards_qs = Card.objects.filter(column=column, id__in=normalized)
    found = set(cards_qs.values_list("id", flat=True))
    expected = set(normalized)
    if found != expected:
        return HttpResponseBadRequest("Lista contém cards inválidos para esta coluna.")

    cards_by_id = {c.id: c for c in cards_qs}
    changed = []
    for idx, cid in enumerate(normalized):
        card = cards_by_id[cid]
        if int(card.position or 0) != idx:
            card.position = idx
            changed.append(card)

    if changed:
        Card.objects.bulk_update(changed, ["position"])

        # Atualiza versão do board para polling refletir mudança (mesma estratégia de criação/movimento)
        board.version += 1
        board.save(update_fields=["version"])  # padrão usado no fluxo de escrita :contentReference[oaicite:3]{index=3}

    return JsonResponse({"ok": True})


# end file boards/views/cards.py
