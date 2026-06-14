# boards/views/columns.py

import json
import re
import requests

from django.http import HttpResponse, JsonResponse, HttpResponseBadRequest
from django.shortcuts import render, get_object_or_404
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required
from django.db import transaction
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
