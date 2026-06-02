# boards/views/secrets.py
"""
Snippets/segredos de card: criar, revelar e remover.

Conteúdo (ex.: curl com chave de API) é criptografado em repouso (Fernet) e só
pode ser revelado pelo autor ou pelos viewers marcados — validação SEMPRE no
servidor. Ver boards/models.py::CardSecret e services/secret_crypto.py.
"""

import logging

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404
from django.template.loader import render_to_string
from django.views.decorators.http import require_POST

from ..models import Card, CardSecret, CardSecretReveal
from ..services.secret_crypto import encrypt_secret, decrypt_secret, SecretCryptoError
from .helpers import _card_secret_context, _board_member_users

logger = logging.getLogger(__name__)


def _user_can_access_card(user, card) -> bool:
    """Mesma regra do card_modal: membro do board (ou criador, em board legado)."""
    board = card.column.board if card.column_id else None
    if board is None:
        return False
    if getattr(user, "is_superuser", False):
        return True
    memberships = board.memberships
    if memberships.exists():
        return memberships.filter(user=user).exists()
    return board.created_by_id == user.id


def _render_secrets_panel(request, card):
    ctx = _card_secret_context(card, request.user)
    ctx["card"] = card
    html = render_to_string(
        "boards/partials/card_secrets_panel.html", ctx, request=request
    )
    return HttpResponse(html)


@login_required
@require_POST
def add_secret(request, card_id):
    card = get_object_or_404(
        Card.objects.select_related("column__board"), id=card_id
    )
    if not _user_can_access_card(request.user, card):
        return HttpResponseForbidden("Sem acesso a este card.")

    content = (request.POST.get("content") or "").strip()
    title = (request.POST.get("title") or "").strip()[:200]
    lang = (request.POST.get("lang") or "curl").strip()[:20]

    if not content:
        return HttpResponse("Conteúdo vazio.", status=400)

    try:
        token = encrypt_secret(content)
    except SecretCryptoError as e:
        logger.error("Falha ao criptografar segredo: %s", e)
        return HttpResponse("Erro de criptografia no servidor.", status=500)

    secret = CardSecret.objects.create(
        card=card,
        author=request.user,
        title=title,
        lang=lang,
        ciphertext=token,
    )

    # viewers: só aceita membros do board (anti-tamper) e nunca o próprio autor
    allowed_ids = {u.id for u in _board_member_users(card.column.board)}
    viewer_ids = []
    for raw in request.POST.getlist("viewers"):
        try:
            i = int(raw)
        except (TypeError, ValueError):
            continue
        if i in allowed_ids and i != request.user.id:
            viewer_ids.append(i)
    if viewer_ids:
        secret.viewers.set(viewer_ids)

    return _render_secrets_panel(request, card)


@login_required
@require_POST
def reveal_secret(request, card_id, secret_id):
    card = get_object_or_404(
        Card.objects.select_related("column__board"), id=card_id
    )
    if not _user_can_access_card(request.user, card):
        return HttpResponseForbidden("Sem acesso a este card.")

    secret = get_object_or_404(
        CardSecret, id=secret_id, card=card, is_active=True
    )

    # gate ESTRITO no servidor — nunca confiar no cliente
    if not secret.can_reveal(request.user):
        return HttpResponseForbidden(
            "Você não tem permissão para revelar este conteúdo."
        )

    try:
        plaintext = decrypt_secret(secret.ciphertext)
    except SecretCryptoError as e:
        logger.error("Falha ao revelar segredo %s: %s", secret_id, e)
        return HttpResponse("Não foi possível descriptografar.", status=500)

    # auditoria: quem revelou e quando
    CardSecretReveal.objects.create(secret=secret, user=request.user)

    html = render_to_string(
        "boards/partials/card_secret_reveal.html",
        {"secret": secret, "plaintext": plaintext},
        request=request,
    )
    return HttpResponse(html)


@login_required
@require_POST
def edit_secret_viewers(request, card_id, secret_id):
    """Atualiza quem pode revelar (só o autor). Mantém o ciphertext intacto."""
    card = get_object_or_404(
        Card.objects.select_related("column__board"), id=card_id
    )
    if not _user_can_access_card(request.user, card):
        return HttpResponseForbidden("Sem acesso a este card.")

    secret = get_object_or_404(
        CardSecret, id=secret_id, card=card, is_active=True
    )
    if not (secret.author_id == request.user.id or request.user.is_superuser):
        return HttpResponseForbidden("Só o autor pode gerenciar o acesso.")

    allowed_ids = {u.id for u in _board_member_users(card.column.board)}
    viewer_ids = []
    for raw in request.POST.getlist("viewers"):
        try:
            i = int(raw)
        except (TypeError, ValueError):
            continue
        if i in allowed_ids and i != secret.author_id:
            viewer_ids.append(i)

    secret.viewers.set(viewer_ids)
    return _render_secrets_panel(request, card)


@login_required
@require_POST
def delete_secret(request, card_id, secret_id):
    card = get_object_or_404(
        Card.objects.select_related("column__board"), id=card_id
    )
    if not _user_can_access_card(request.user, card):
        return HttpResponseForbidden("Sem acesso a este card.")

    secret = get_object_or_404(
        CardSecret, id=secret_id, card=card, is_active=True
    )

    # só o autor (ou superuser) remove
    if not (secret.author_id == request.user.id or request.user.is_superuser):
        return HttpResponseForbidden("Só o autor pode remover este segredo.")

    # soft-delete (regra do projeto — nunca delete físico)
    secret.is_active = False
    secret.save(update_fields=["is_active"])

    return _render_secrets_panel(request, card)
