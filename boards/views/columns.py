# boards/views/columns.py

import json
import logging
import re
import requests

logger = logging.getLogger("boards.import_trello")

from django.http import HttpResponse, JsonResponse, HttpResponseBadRequest
from django.shortcuts import render, get_object_or_404
from django.views.decorators.http import require_POST, require_http_methods
from django.contrib.auth.decorators import login_required
from django.db import transaction, models
from django.db.models import Count, Exists
from django.utils import timezone
from django.utils.html import escape

from ..forms import ColumnForm
from .helpers import (
    # mantém só helpers/models que realmente estão em helpers.py
    # exemplo:
    _actor_label,
    _log_board,
    _log_card,
    Board,
    Column,
    Card,
    BoardMembership,
)
from .cards import _user_can_edit_board, _deny_read_only



def add_column(request, board_id):
    board = get_object_or_404(Board, id=board_id)

    if request.method == "POST":
        form = ColumnForm(request.POST)
        if form.is_valid():
            column = form.save(commit=False)
            column.board = board
            column.position = board.columns.count()
            column.save()
            board.version += 1
            board.save(update_fields=["version"])


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

    board = column.board
    board.version += 1
    board.save(update_fields=["version"])

    actor = _actor_label(request)
    _log_board(
        column.board,
        request,
        f"<p><strong>{actor}</strong> alterou o tema da coluna <strong>{escape(column.name)}</strong> de <strong>{escape(old_theme)}</strong> para <strong>{escape(theme)}</strong>.</p>",
    )

    return render(request, "boards/partials/column_item.html", {"column": column})


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

        board.version += 1
        board.save(update_fields=["version"])


    actor = _actor_label(request)
    _log_board(
        board,
        request,
        f"<p><strong>{actor}</strong> reordenou colunas no quadro <strong>{escape(board.name)}</strong>.</p>",
    )

    return JsonResponse({"ok": True})

@require_POST
def rename_column(request, column_id):
    column = get_object_or_404(Column, id=column_id)
    board = column.board
    actor = _actor_label(request)

    old_name = column.name
    name = request.POST.get("name", "").strip()
    if not name:
        return HttpResponse("Nome inválido", status=400)
    
    column.name = name
    column.save(update_fields=["name"])
    board.version += 1
    board.save(update_fields=["version"])
    
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
    


def delete_column(request, column_id):
    if request.method != "POST":
        return HttpResponseBadRequest("Método inválido.")

    try:
        column = Column.objects.get(id=column_id, is_deleted=False)
    except Column.DoesNotExist:
        return HttpResponseBadRequest("Coluna não encontrada.")


    board = column.board
    actor = _actor_label(request)

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
    board.version += 1
    board.save(update_fields=["version"])

    Card.objects.filter(column=column, is_deleted=False).update(is_deleted=True, deleted_at=now)
    return HttpResponse("")


# alias de compatibilidade
column_delete = delete_column


# ============================================================
# MOVER COLUNA (entre quadros ou reordenando dentro do mesmo)
# ------------------------------------------------------------
# Move a coluna inteira — e, junto, todos os cards nela — para o quadro
# escolhido, na posição escolhida (1 = primeira da esquerda). Só lista
# quadros onde o usuário é dono (owner) ou editor.
# ============================================================

def _editable_boards_for(user):
    """Quadros onde `user` pode editar, ordenados por mais recente.

    SÓ retorna quadros ATIVOS (Board.objects já exclui arquivados/excluídos) em
    que o usuário é DONO (owner) ou EDITOR — nunca apenas visualizador, e NUNCA
    quadros de terceiros. Sem bypass de staff: mover coluna é ação de usuário,
    não de admin, então mesmo staff só enxerga os próprios quadros aqui.
    Inclui quadros legados sem membership criados pelo próprio usuário.
    """
    qs = Board.objects.all()  # ActiveBoardManager: is_deleted=False, is_archived=False

    editable_ids = set(
        BoardMembership.objects.filter(
            user=user,
            board__is_deleted=False,
            role__in=[BoardMembership.Role.OWNER, BoardMembership.Role.EDITOR],
        ).values_list("board_id", flat=True)
    )

    legacy_ids = set(
        qs.filter(created_by_id=user.id)
        .annotate(has_members=Exists(
            BoardMembership.objects.filter(board=models.OuterRef("pk"))
        ))
        .filter(has_members=False)
        .values_list("id", flat=True)
    )

    all_ids = editable_ids | legacy_ids
    return list(qs.filter(id__in=all_ids).order_by("-created_at"))


@login_required
@require_http_methods(["GET"])
def move_column_modal(request, column_id):
    """Modal pequeno para escolher quadro de destino + posição da coluna."""
    column = get_object_or_404(Column, id=column_id, is_deleted=False)

    if not _user_can_edit_board(request.user, column.board):
        return _deny_read_only(request)

    boards = _editable_boards_for(request.user)

    # nº de colunas por quadro (para montar o seletor de posição no front).
    # Exclui a própria coluna que está sendo movida (não conta como "slot ocupado").
    counts = {
        row["board_id"]: row["n"]
        for row in (
            Column.objects.filter(
                board_id__in=[b.id for b in boards],
                is_deleted=False,
            )
            .exclude(id=column.id)
            .values("board_id")
            .annotate(n=Count("id"))
        )
    }

    boards_payload = [
        {"id": b.id, "name": b.name, "slots": counts.get(b.id, 0) + 1}
        for b in boards
    ]

    return render(
        request,
        "boards/partials/move_column_modal.html",
        {
            "column": column,
            "current_board_id": column.board_id,
            "boards_json": json.dumps(boards_payload, ensure_ascii=False),
        },
    )


@login_required
@require_POST
def move_column(request, column_id):
    """Move a coluna (e todos os cards) para o quadro/posição escolhidos."""
    column = get_object_or_404(Column, id=column_id, is_deleted=False)

    try:
        data = json.loads(request.body.decode("utf-8"))
        target_board_id = int(data.get("target_board_id"))
        new_position = int(data.get("new_position", 1))  # 1-based vindo da UI
    except Exception:
        return JsonResponse({"ok": False, "error": "Payload inválido."}, status=400)

    old_board = column.board
    target_board = get_object_or_404(Board, id=target_board_id, is_deleted=False)

    # permissão em origem E destino
    if not _user_can_edit_board(request.user, old_board) or not _user_can_edit_board(request.user, target_board):
        return _deny_read_only(request, as_json=True)

    actor = _actor_label(request)
    same_board = old_board.id == target_board.id

    with transaction.atomic():
        # colunas do destino (sem a que está sendo movida), em ordem
        siblings = list(
            Column.objects.filter(board=target_board, is_deleted=False)
            .exclude(id=column.id)
            .order_by("position")
        )

        # clamp do índice 0-based
        idx = new_position - 1
        if idx < 0:
            idx = 0
        if idx > len(siblings):
            idx = len(siblings)

        # reatribui o quadro (os cards seguem junto via FK column)
        column.board = target_board

        # reindexa o destino inserindo a coluna na posição escolhida
        new_order = siblings[:idx] + [column] + siblings[idx:]
        for i, c in enumerate(new_order):
            if c.position != i or c.id == column.id:
                c.position = i
                c.save(update_fields=["position", "board"] if c.id == column.id else ["position"])

        # se mudou de quadro, reindexa também o quadro de origem
        if not same_board:
            for i, c in enumerate(
                Column.objects.filter(board=old_board, is_deleted=False).order_by("position")
            ):
                if c.position != i:
                    c.position = i
                    c.save(update_fields=["position"])

        old_board.version += 1
        old_board.save(update_fields=["version"])
        if not same_board:
            target_board.version += 1
            target_board.save(update_fields=["version"])

    if same_board:
        _log_board(
            target_board,
            request,
            f"<p><strong>{actor}</strong> moveu a coluna <strong>{escape(column.name)}</strong> "
            f"para a posição {new_position}.</p>",
        )
    else:
        _log_board(
            old_board,
            request,
            f"<p><strong>{actor}</strong> moveu a coluna <strong>{escape(column.name)}</strong> "
            f"(com todos os cards) para o quadro <strong>{escape(target_board.name)}</strong>.</p>",
        )
        _log_board(
            target_board,
            request,
            f"<p><strong>{actor}</strong> recebeu a coluna <strong>{escape(column.name)}</strong> "
            f"(com todos os cards) vinda do quadro <strong>{escape(old_board.name)}</strong>.</p>",
        )

    return JsonResponse({
        "ok": True,
        "board_url": f"/board/{target_board.id}/",
        "same_board": same_board,
    })


import csv
import json as _json
from collections import defaultdict
from django.utils.html import strip_tags as _strip_tags
from ..models import Checklist, ChecklistItem, CardLog


@login_required
def export_column(request, column_id):
    column = get_object_or_404(Column, id=column_id, is_deleted=False)
    fmt = request.GET.get("fmt", "csv").lower()

    cards = list(
        Card.objects.filter(column=column, is_deleted=False)
        .order_by("position")
    )

    fields = [
        "posicao", "titulo", "tags", "descricao",
        "data_inicio", "data_aviso", "data_vencimento",
        "entregue", "arquivado",
    ]

    def card_row_csv(card, i):
        return {
            "posicao": i + 1,
            "titulo": card.title or "",
            "tags": card.tags or "",
            "descricao": _strip_tags(card.description or "").strip(),
            "data_inicio": str(card.start_date) if card.start_date else "",
            "data_aviso": str(card.due_warn_date) if card.due_warn_date else "",
            "data_vencimento": str(card.due_date) if card.due_date else "",
            "entregue": "sim" if getattr(card, "is_delivered", False) else "nao",
            "arquivado": "sim" if getattr(card, "is_archived", False) else "nao",
        }

    safe_name = column.name.replace(" ", "_")[:40]

    if fmt == "json":
        card_ids = [c.id for c in cards]

        # Checklists + itens
        checklists_map = defaultdict(list)
        for cl in (
            Checklist.objects
            .filter(card_id__in=card_ids)
            .prefetch_related("items")
            .order_by("card_id", "position")
        ):
            checklists_map[cl.card_id].append({
                "titulo": cl.title,
                "posicao": cl.position,
                "itens": [
                    {
                        "texto": item.text,
                        "feito": item.is_done,
                        "posicao": item.position,
                    }
                    for item in cl.items.order_by("position")
                ],
            })

        # Atividades (logs)
        logs_map = defaultdict(list)
        for log in (
            CardLog.objects
            .filter(card_id__in=card_ids)
            .select_related("actor", "actor__profile")
            .order_by("card_id", "created_at")
        ):
            actor = log.actor
            actor_handle = ""
            if actor:
                p = getattr(actor, "profile", None)
                actor_handle = getattr(p, "handle", "") or actor.email or ""
            logs_map[log.card_id].append({
                "texto": log.content_text or "",
                "autor": actor_handle,
                "criado_em": log.created_at.strftime("%Y-%m-%d %H:%M"),
            })

        def card_full(card, i):
            return {
                "posicao": i + 1,
                "titulo": card.title or "",
                "tags": card.tags or "",
                "tag_colors": card.tag_colors or {},
                "descricao": card.description or "",
                "data_inicio": str(card.start_date) if card.start_date else "",
                "data_aviso": str(card.due_warn_date) if card.due_warn_date else "",
                "data_vencimento": str(card.due_date) if card.due_date else "",
                "entregue": card.is_delivered,
                "arquivado": card.is_archived,
                "checklists": checklists_map.get(card.id, []),
                "atividades": logs_map.get(card.id, []),
            }

        payload = {
            "_formato": "nossotrello-coluna-v1",
            "coluna": column.name,
            "quadro": column.board.name,
            "exportado_em": timezone.now().strftime("%Y-%m-%d %H:%M"),
            "cards": [card_full(c, i) for i, c in enumerate(cards)],
        }
        resp = HttpResponse(
            _json.dumps(payload, ensure_ascii=False, indent=2),
            content_type="application/json; charset=utf-8",
        )
        resp["Content-Disposition"] = f'attachment; filename="{safe_name}.json"'
        return resp

    # CSV (default)
    rows = [card_row_csv(c, i) for i, c in enumerate(cards)]
    resp = HttpResponse(content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="{safe_name}.csv"'
    resp.write("\ufeff")  # BOM para Excel abrir UTF-8 corretamente
    writer = csv.DictWriter(resp, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
    return resp


# ============================================================
# IMPORT COLUMN (nossotrello-coluna-v1 JSON)
# ============================================================

@login_required
def import_column_form(request, board_id):
    """Retorna o modal de import de coluna (nosso formato JSON)."""
    board = get_object_or_404(Board, id=board_id)
    if not BoardMembership.objects.filter(board=board, user=request.user).exists():
        return HttpResponse("Acesso negado.", status=403)
    return render(request, "boards/partials/import_column_modal.html", {"board": board})


@login_required
@require_POST
def import_column_execute(request, board_id):
    """Processa o upload de um JSON (nossotrello-coluna-v1) e cria a coluna no quadro."""
    board = get_object_or_404(Board, id=board_id)
    if not BoardMembership.objects.filter(board=board, user=request.user).exists():
        return JsonResponse({"error": "Acesso negado."}, status=403)

    uploaded = request.FILES.get("file")
    if not uploaded:
        return JsonResponse({"error": "Nenhum arquivo enviado."}, status=400)

    try:
        raw = uploaded.read().decode("utf-8-sig")
        data = _json.loads(raw)
    except Exception:
        return JsonResponse({"error": "Arquivo JSON inválido."}, status=400)

    if data.get("_formato") != "nossotrello-coluna-v1":
        return JsonResponse({"error": "Formato não reconhecido. Use um arquivo exportado deste sistema."}, status=400)

    col_name = data.get("coluna") or "Coluna importada"
    cards_data = data.get("cards") or []

    # Posição: após a última coluna existente
    last_pos = (
        Column.objects.filter(board=board, is_deleted=False)
        .order_by("-position")
        .values_list("position", flat=True)
        .first()
    ) or 0

    with transaction.atomic():
        column = Column.objects.create(
            board=board,
            name=col_name,
            position=last_pos + 1,
        )

        for i, cd in enumerate(cards_data):
            from datetime import date as _date
            def _parse_date(v):
                if not v:
                    return None
                try:
                    return _date.fromisoformat(str(v))
                except Exception:
                    return None

            card = Card.all_objects.create(
                column=column,
                title=(cd.get("titulo") or "").strip() or f"Card {i+1}",
                description=cd.get("descricao") or "",
                tags=cd.get("tags") or "",
                tag_colors=cd.get("tag_colors") or {},
                start_date=_parse_date(cd.get("data_inicio")),
                due_warn_date=_parse_date(cd.get("data_aviso")),
                due_date=_parse_date(cd.get("data_vencimento")),
                is_delivered=bool(cd.get("entregue")),
                is_archived=bool(cd.get("arquivado")),
                position=i,
            )

            for cl_data in (cd.get("checklists") or []):
                cl = Checklist.objects.create(
                    card=card,
                    title=cl_data.get("titulo") or "Checklist",
                    position=cl_data.get("posicao") or 0,
                )
                for j, item_data in enumerate(cl_data.get("itens") or []):
                    ChecklistItem.objects.create(
                        card=card,
                        checklist=cl,
                        text=item_data.get("texto") or "",
                        is_done=bool(item_data.get("feito")),
                        position=item_data.get("posicao") or j,
                    )

        board.version += 1
        board.save(update_fields=["version"])

    board_url = f"/board/{board.id}/"
    return JsonResponse({
        "ok": True,
        "board_url": board_url,
        "coluna": col_name,
        "cards_criados": len(cards_data),
    })


# ============================================================
# IMPORT TRELLO JSON
# ============================================================

@login_required
def import_trello_form(request):
    """Modal para importar um JSON exportado do Trello."""
    return render(request, "boards/partials/import_trello_modal.html")


@login_required
@require_POST
def import_trello_execute(request):
    """Processa o JSON do Trello e cria um novo quadro."""
    uploaded = request.FILES.get("file")
    if not uploaded:
        return JsonResponse({"error": "Nenhum arquivo enviado."}, status=400)

    try:
        raw = uploaded.read().decode("utf-8-sig")
        data = _json.loads(raw)
    except Exception:
        return JsonResponse({"error": "Arquivo JSON inválido."}, status=400)

    try:
        result = _build_board_from_trello(data, request.user)
    except ValueError as e:
        return JsonResponse({"error": str(e)}, status=400)
    return JsonResponse({"ok": True, **result})


@login_required
@require_POST
def import_trello_from_url(request):
    """
    Baixa o JSON do board DIRETO pela URL (server-side) e importa, sem o usuário
    salvar/enviar arquivo. Funciona em board PÚBLICO. Em board PRIVADO o Trello
    responde 401/HTML (o servidor não tem a sessão do usuário) -> instrui a 2ª opção.
    """
    url = (request.POST.get("url") or "").strip()
    m = re.search(r"trello\.com/b/([A-Za-z0-9]+)", url)
    if not m:
        # Link de CARD (…/c/…): tenta descobrir o quadro dono do card.
        mc = re.search(r"trello\.com/c/([A-Za-z0-9]+)", url)
        if mc:
            short = _resolve_board_from_card(mc.group(1))
            if short:
                m = re.match(r"([A-Za-z0-9]+)", short)
            else:
                return JsonResponse({
                    "error": "Isso é um link de CARD (…/c/…). Para importar eu preciso do link do "
                             "QUADRO inteiro (…/b/…). Abra o quadro no Trello e copie a URL da barra "
                             "de endereço — ou use a 2ª opção (Abrir JSON → salvar → enviar).",
                }, status=400)
        if not m:
            return JsonResponse({"error": "Cole uma URL de board do Trello (…/b/…)."}, status=400)

    json_url = f"https://trello.com/b/{m.group(1)}.json"
    try:
        r = requests.get(json_url, timeout=20, headers={"User-Agent": "Mozilla/5.0 (NossoTrello)"})
    except Exception:
        return JsonResponse({"error": "Não consegui acessar o Trello agora. Tente de novo."}, status=502)

    head = (r.text or "")[:80].strip().lower()
    if r.status_code in (401, 403) or "unauthorized" in head or head.startswith("<"):
        return JsonResponse({
            "error": "Board PRIVADO: o servidor não consegue baixar sozinho (o Trello exige a sua "
                     "sessão). Use a 2ª opção: clique em \"Abrir JSON\", salve o arquivo e envie aqui."
        }, status=400)

    try:
        data = r.json()
    except Exception:
        return JsonResponse({"error": "O Trello não devolveu um JSON válido. Use a 2ª opção."}, status=400)

    try:
        result = _build_board_from_trello(data, request.user)
    except ValueError as e:
        return JsonResponse({"error": str(e)}, status=400)
    return JsonResponse({"ok": True, **result})


def _resolve_board_from_card(card_short):
    """A partir do shortLink de um card público, descobre o shortLink do quadro.

    Em card privado o Trello responde 401/HTML -> retorna None (cai na mensagem
    que orienta a colar o link do quadro).
    """
    try:
        r = requests.get(
            f"https://trello.com/c/{card_short}.json",
            timeout=15, headers={"User-Agent": "Mozilla/5.0 (NossoTrello)"},
        )
        head = (r.text or "")[:80].strip().lower()
        if r.status_code != 200 or head.startswith("<"):
            return None
        data = r.json()
    except Exception:
        return None
    board = data.get("board") or {}
    return board.get("shortLink") or data.get("idBoard") or None


def _build_board_from_trello(data, user):
    """Cria um novo board a partir do dict de export do Trello. Levanta ValueError se inválido."""
    if not isinstance(data.get("lists"), list) or not isinstance(data.get("cards"), list):
        raise ValueError("Não parece ser um export válido do Trello (faltam lists/cards).")

    board_name = data.get("name") or "Importado do Trello"
    now_str = timezone.now().strftime("%d/%m/%Y %H:%M")
    new_board_name = f"IMPORTANDO DO TRELLO EM {now_str}: {board_name}"[:200]

    lists_raw = sorted(
        [l for l in data["lists"] if not l.get("closed")],
        key=lambda x: x.get("pos", 0),
    )
    cards_raw = [c for c in data["cards"] if not c.get("closed")]

    cards_by_list = defaultdict(list)
    for c in cards_raw:
        cards_by_list[c["idList"]].append(c)

    checklists_map = {cl["id"]: cl for cl in (data.get("checklists") or [])}

    from datetime import datetime as _dt

    def _parse_due(tc):
        v = tc.get("due")
        if not v:
            return None
        try:
            return _dt.fromisoformat(v.replace("Z", "+00:00")).date()
        except Exception:
            return None

    # IMPORTANTE: quadros do Trello podem ter MILHARES de cards. Fazer um INSERT
    # por linha contra o RDS (us-east-1) estoura o timeout do gunicorn. Por isso
    # tudo aqui é montado em memória e gravado com bulk_create (poucos round-trips).
    with transaction.atomic():
        new_board = Board.objects.create(name=new_board_name, created_by=user)
        BoardMembership.objects.get_or_create(
            board=new_board, user=user,
            defaults={"role": BoardMembership.Role.OWNER},
        )

        # 1) Colunas
        col_objs = [
            Column(board=new_board, name=lst["name"], position=i)
            for i, lst in enumerate(lists_raw)
        ]
        Column.objects.bulk_create(col_objs)
        columns_by_list = {lst["id"]: col for lst, col in zip(lists_raw, col_objs)}

        # 2) Cards (paralelo a card_tc p/ ligar checklists depois)
        card_objs, card_tc = [], []
        for lst in lists_raw:
            col = columns_by_list[lst["id"]]
            col_cards = sorted(cards_by_list.get(lst["id"], []), key=lambda x: x.get("pos", 0))
            for card_pos, tc in enumerate(col_cards):
                labels = tc.get("labels") or []
                tag_names = ", ".join(lbl["name"] for lbl in labels if lbl.get("name"))
                card_objs.append(Card(
                    column=col,
                    created_by=user,
                    title=(tc.get("name") or "").strip() or f"Card {card_pos+1}",
                    description=tc.get("desc") or "",
                    tags=tag_names,
                    due_date=_parse_due(tc),
                    position=card_pos,
                ))
                card_tc.append(tc)
        Card.all_objects.bulk_create(card_objs, batch_size=500)

        # 3) Checklists (paralelo a card/cl_data p/ ligar itens depois)
        cl_objs, cl_card, cl_data_ref = [], [], []
        for card, tc in zip(card_objs, card_tc):
            for cl_id in (tc.get("idChecklists") or []):
                cl_data = checklists_map.get(cl_id)
                if not cl_data:
                    continue
                cl_objs.append(Checklist(card=card, title=cl_data.get("name") or "Checklist", position=0))
                cl_card.append(card)
                cl_data_ref.append(cl_data)
        if cl_objs:
            Checklist.objects.bulk_create(cl_objs, batch_size=500)

        # 4) Itens de checklist
        item_objs = []
        for cl, card, cl_data in zip(cl_objs, cl_card, cl_data_ref):
            for j, item in enumerate(sorted(cl_data.get("checkItems") or [], key=lambda x: x.get("pos", 0))):
                item_objs.append(ChecklistItem(
                    card=card, checklist=cl,
                    text=item.get("name") or "",
                    is_done=(item.get("state") == "complete"),
                    position=j,
                ))
        if item_objs:
            ChecklistItem.objects.bulk_create(item_objs, batch_size=1000)

    return {
        "board_url": f"/board/{new_board.id}/",
        "board_name": new_board_name,
        "colunas": len(lists_raw),
        "cards": len(cards_raw),
    }


# ============================================================
# IMPORT TRELLO EM LOTES (quadros gigantes)
# ------------------------------------------------------------
# O navegador faz o parse do JSON grande e envia em pedaços:
#   1) /import/trello/start/  -> cria board + colunas, devolve o mapa de colunas
#   2) /import/trello/batch/  -> grava um lote de cards (+checklists) via bulk_create
# Assim não há upload gigante, nem json.loads de 48MB no servidor, nem timeout.
# ============================================================
@login_required
@require_POST
def import_trello_start(request):
    try:
        payload = _json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"error": "Payload inválido."}, status=400)

    name = (payload.get("name") or "Importado do Trello").strip()
    lists = payload.get("lists") or []
    if not isinstance(lists, list) or not lists:
        return JsonResponse({"error": "Sem listas para importar."}, status=400)

    now_str = timezone.now().strftime("%d/%m/%Y %H:%M")
    new_board_name = f"IMPORTANDO DO TRELLO EM {now_str}: {name}"[:200]

    with transaction.atomic():
        board = Board.objects.create(name=new_board_name, created_by=request.user)
        BoardMembership.objects.get_or_create(
            board=board, user=request.user,
            defaults={"role": BoardMembership.Role.OWNER},
        )
        col_objs = [
            Column(board=board, name=(l.get("name") or "Lista")[:255], position=i)
            for i, l in enumerate(lists)
        ]
        Column.objects.bulk_create(col_objs)
        columns = {str(l.get("id")): col.id for l, col in zip(lists, col_objs)}

    logger.info("import.start user=%s board=%s '%s' colunas=%s",
                request.user.id, board.id, new_board_name, len(col_objs))
    return JsonResponse({
        "board_id": board.id,
        "board_url": f"/board/{board.id}/",
        "board_name": new_board_name,
        "columns": columns,
    })


@login_required
@require_POST
def import_trello_batch(request):
    try:
        payload = _json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"error": "Payload inválido."}, status=400)

    board_id = payload.get("board_id")
    board = get_object_or_404(Board, id=board_id, created_by=request.user)
    cards_in = payload.get("cards") or []
    if not isinstance(cards_in, list):
        return JsonResponse({"error": "Lote inválido."}, status=400)

    # só colunas deste board (anti-adulteração de column_id)
    valid_cols = set(Column.objects.filter(board=board).values_list("id", flat=True))

    from datetime import datetime as _dt

    def _due(v):
        if not v:
            return None
        try:
            return _dt.fromisoformat(str(v).replace("Z", "+00:00")).date()
        except Exception:
            return None

    card_objs, card_meta = [], []
    for c in cards_in:
        try:
            col_id = int(c.get("column_id"))
        except Exception:
            continue
        if col_id not in valid_cols:
            continue
        labels = c.get("labels") or []
        tags = ", ".join(str(x) for x in labels if x)[:255]
        card_objs.append(Card(
            column_id=col_id,
            created_by=request.user,
            title=((c.get("name") or "").strip() or "Card")[:255],
            description=c.get("desc") or "",
            tags=tags,
            due_date=_due(c.get("due")),
            position=int(c.get("pos") or 0),
        ))
        card_meta.append(c)

    n_cl = n_items = 0
    try:
        with transaction.atomic():
            if card_objs:
                Card.all_objects.bulk_create(card_objs, batch_size=500)

                # checklists + itens
                cl_objs, cl_items = [], []
                for card, meta in zip(card_objs, card_meta):
                    for cl in (meta.get("checklists") or []):
                        cl_objs.append(Checklist(card=card, title=(cl.get("name") or "Checklist")[:255], position=0))
                        cl_items.append(cl.get("items") or [])
                if cl_objs:
                    Checklist.objects.bulk_create(cl_objs, batch_size=500)
                    n_cl = len(cl_objs)
                    item_objs = []
                    for cl, items in zip(cl_objs, cl_items):
                        for j, it in enumerate(items):
                            item_objs.append(ChecklistItem(
                                card=cl.card, checklist=cl,
                                text=((it.get("name") or "") if isinstance(it, dict) else str(it))[:255],
                                is_done=bool(it.get("done")) if isinstance(it, dict) else False,
                                position=j,
                            ))
                    if item_objs:
                        ChecklistItem.objects.bulk_create(item_objs, batch_size=1000)
                        n_items = len(item_objs)

                board.version = (board.version or 0) + 1
                board.save(update_fields=["version"])
    except Exception:
        logger.exception("import.batch FALHOU board=%s cards_no_lote=%s", board.id, len(card_objs))
        return JsonResponse(
            {"error": "Falha ao gravar este lote no servidor (veja os logs). Tente de novo."},
            status=500,
        )

    logger.info("import.batch board=%s cards=%s checklists=%s itens=%s",
                board.id, len(card_objs), n_cl, n_items)
    # devolve tcid -> nosso id, p/ o cliente ligar as actions depois
    id_map = {c.get("tcid"): card.id for c, card in zip(card_meta, card_objs) if c.get("tcid")}
    return JsonResponse({"created": len(card_objs), "id_map": id_map})


@login_required
@require_POST
def import_trello_actions(request):
    """Grava um lote de actions do Trello como acompanhamento (CardLog).

    Cada item: {card_id, html, text, date(iso)}. Preserva a data original.
    """
    from .helpers import Card  # noqa
    from ..models import CardLog

    try:
        payload = _json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"error": "Payload inválido."}, status=400)

    board_id = payload.get("board_id")
    board = get_object_or_404(Board, id=board_id, created_by=request.user)
    logs_in = payload.get("logs") or []
    valid_cards = set(
        Card.all_objects.filter(column__board=board).values_list("id", flat=True)
    )

    from datetime import datetime as _dt

    def _dt_parse(v):
        try:
            d = _dt.fromisoformat(str(v).replace("Z", "+00:00"))
            if timezone.is_naive(d):
                d = timezone.make_aware(d, timezone.utc)
            return d
        except Exception:
            return None

    try:
        log_objs, dates = [], []
        for it in logs_in:
            try:
                cid = int(it.get("card_id"))
            except Exception:
                continue
            if cid not in valid_cards:
                continue
            log_objs.append(CardLog(
                card_id=cid, actor=None,
                content=it.get("html") or "",
                content_text=(it.get("text") or "")[:5000],
            ))
            dates.append(_dt_parse(it.get("date")))
        if log_objs:
            CardLog.objects.bulk_create(log_objs, batch_size=1000)
            to_fix = [lo for lo, d in zip(log_objs, dates) if d]
            for lo, d in zip(log_objs, dates):
                if d:
                    lo.created_at = d
            if to_fix:
                CardLog.objects.bulk_update(to_fix, ["created_at"], batch_size=1000)
    except Exception:
        logger.exception("import.actions FALHOU board=%s", board.id)
        return JsonResponse({"error": "Falha ao gravar acompanhamentos."}, status=500)

    logger.info("import.actions board=%s logs=%s", board.id, len(log_objs))
    return JsonResponse({"created": len(log_objs)})


# ============================================================
# LAZY-LOAD de cards (boards grandes): carrega +N cards da coluna sob demanda
# (htmx hx-trigger="revealed"). Mantém o board leve no load inicial.
# ============================================================
@login_required
def column_cards_more(request, column_id):
    from django.template.loader import render_to_string

    column = get_object_or_404(Column, id=column_id, is_deleted=False)
    board = column.board
    allowed = (
        board.created_by_id == request.user.id
        or BoardMembership.objects.filter(board=board, user=request.user).exists()
    )
    if not allowed:
        return HttpResponse("", status=403)

    try:
        offset = max(0, int(request.GET.get("offset") or 0))
    except Exception:
        offset = 0
    PAGE = 20

    cards = list(
        Card.objects.filter(column=column, is_archived=False)
        .order_by("position", "id")[offset:offset + PAGE + 1]
    )
    has_more = len(cards) > PAGE
    cards = cards[:PAGE]

    html = render_to_string(
        "boards/partials/column_cards_more.html",
        {"cards": cards, "column": column, "next_offset": offset + PAGE, "has_more": has_more},
        request=request,
    )
    return HttpResponse(html)
