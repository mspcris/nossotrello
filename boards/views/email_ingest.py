# boards/views/email_ingest.py
"""
"Criar Card From Email" — configuração por quadro (modal no ☰) + sync manual.
"""
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_http_methods

from ..models import Board, BoardEmailIngest
from ..permissions import can_edit_board
from ..services.email_ingest import sync_one
from ..services.secret_crypto import encrypt_secret


def _active_columns(board):
    return board.columns.filter(is_deleted=False).order_by("position")


@login_required
def email_ingest_config(request, board_id):
    board = get_object_or_404(Board, id=board_id)
    if not can_edit_board(request.user, board):
        return HttpResponse("Sem permissão.", status=403)

    columns = _active_columns(board)
    config = BoardEmailIngest.objects.filter(board=board).first()

    if request.method == "POST":
        if not columns.exists():
            return HttpResponse("É preciso ao menos uma coluna.", status=400)

        column = columns.filter(id=request.POST.get("target_column")).first()
        if not column:
            return render(
                request,
                "boards/partials/email_ingest_modal.html",
                {"board": board, "columns": columns, "config": config,
                 "error": "Selecione uma coluna válida."},
            )

        if config is None:
            config = BoardEmailIngest(board=board, created_by=request.user)

        config.target_column = column
        config.protocol = "pop" if request.POST.get("protocol") == "pop" else "imap"
        config.imap_host = (request.POST.get("imap_host") or "").strip()
        config.imap_port = int(request.POST.get("imap_port") or 993)
        config.use_ssl = request.POST.get("use_ssl") == "on"
        config.email_user = (request.POST.get("email_user") or "").strip()
        config.sync_interval_minutes = max(
            1, int(request.POST.get("sync_interval_minutes") or 15)
        )
        config.is_active = request.POST.get("is_active") == "on"

        pwd = request.POST.get("password") or ""
        if pwd:
            config.password_encrypted = encrypt_secret(pwd)

        config.save()
        # devolve o modal já em modo "salvo", mantendo o botão de sync
        return render(
            request,
            "boards/partials/email_ingest_modal.html",
            {"board": board, "columns": columns, "config": config,
             "saved": True},
        )

    # GET
    if not columns.exists():
        return render(
            request,
            "boards/partials/email_ingest_modal.html",
            {"board": board, "no_columns": True},
        )
    return render(
        request,
        "boards/partials/email_ingest_modal.html",
        {"board": board, "columns": columns, "config": config},
    )


@login_required
@require_http_methods(["POST"])
def email_ingest_sync_now(request, board_id):
    board = get_object_or_404(Board, id=board_id)
    if not can_edit_board(request.user, board):
        return HttpResponse("Sem permissão.", status=403)

    config = BoardEmailIngest.objects.filter(board=board).first()
    if not config:
        return HttpResponse(
            '<div class="ei-result ei-result--warn">Configure e salve primeiro.</div>'
        )

    created, err = sync_one(config)
    if err:
        return HttpResponse(
            f'<div class="ei-result ei-result--err">Erro: {err}</div>'
        )
    if created == 0:
        return HttpResponse(
            '<div class="ei-result ei-result--ok">Sincronizado. Nenhum e-mail novo '
            '(na 1ª vez, fica só o ponto de partida — novos e-mails viram cards).</div>'
        )
    return HttpResponse(
        f'<div class="ei-result ei-result--ok">{created} card(s) criado(s). ✅</div>'
    )
