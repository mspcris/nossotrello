"""Emails enviados pelo pipeline de moderação e por ações de banimento."""
from __future__ import annotations

import logging
from typing import Optional

from django.conf import settings

from boards.services.notifications import send_email_notification

logger = logging.getLogger(__name__)


_KIND_LABEL = {
    "social_post": "publicação",
    "social_comment": "comentário",
    "chat_message": "mensagem no chat",
    "user_handle": "handle (@)",
    "user_name": "nome de exibição",
    "user_bio": "bio do perfil",
}


def _to(author) -> str:
    return (getattr(author, "email", "") or "").strip()


def _site_url() -> str:
    return (getattr(settings, "SITE_URL", "") or "").rstrip("/")


def _preview(text: str, limit: int = 240) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "…"


def send_block_email(
    *, author, kind: str, terms_clause: str, preview_text: str, case_id: Optional[int]
) -> None:
    email = _to(author)
    if not email:
        return
    kind_label = _KIND_LABEL.get(kind, "conteúdo")
    body = (
        f"Olá,\n\n"
        f"Sua {kind_label} foi BLOQUEADA automaticamente por violar a cláusula "
        f"{terms_clause} dos Termos de Uso do NossoTrello.\n\n"
        f"Trecho bloqueado:\n«{_preview(preview_text)}»\n\n"
        f"Se você acha que isso foi um erro, responda este email — um moderador "
        f"vai revisar o caso (referência #{case_id or '-'}).\n\n"
        f"Você pode reler os Termos de Uso em {_site_url()}/legal/termos/."
    )
    send_email_notification(
        to_email=email,
        subject=f"Sua {kind_label} foi bloqueada pela política do NossoTrello",
        body=body,
        use_social=True,
        cta_url=f"{_site_url()}/legal/termos/",
        cta_label="Ver Termos de Uso",
    )


def send_under_review_email(
    *, author, kind: str, preview_text: str, case_id: Optional[int]
) -> None:
    email = _to(author)
    if not email:
        return
    kind_label = _KIND_LABEL.get(kind, "conteúdo")
    body = (
        f"Olá,\n\n"
        f"Sua {kind_label} está sob análise por nossa equipe de moderação "
        f"(referência #{case_id or '-'}). Enquanto isso, ela fica oculta dos "
        f"demais usuários — só você consegue vê-la.\n\n"
        f"Trecho em análise:\n«{_preview(preview_text)}»\n\n"
        f"Vamos te avisar por email assim que a decisão for tomada."
    )
    send_email_notification(
        to_email=email,
        subject="Sua publicação está sob análise",
        body=body,
        use_social=True,
        cta_url=f"{_site_url()}/social/meus-em-analise/",
        cta_label="Ver minhas publicações em análise",
    )


def send_human_decision_email(
    *, author, kind: str, approved: bool, terms_clause: str, notes: str,
    preview_text: str, case_id: Optional[int],
) -> None:
    email = _to(author)
    if not email:
        return
    kind_label = _KIND_LABEL.get(kind, "conteúdo")
    if approved:
        subject = f"Sua {kind_label} foi liberada"
        body = (
            f"Olá,\n\n"
            f"Boa notícia: sua {kind_label} foi analisada e LIBERADA por nossa "
            f"equipe (referência #{case_id or '-'}). Ela já está visível no feed.\n\n"
            f"Observações do moderador:\n{notes or '(sem observações)'}"
        )
    else:
        subject = f"Sua {kind_label} foi removida pela moderação"
        body = (
            f"Olá,\n\n"
            f"Sua {kind_label} foi REMOVIDA por violar a cláusula {terms_clause} "
            f"dos Termos de Uso (referência #{case_id or '-'}).\n\n"
            f"Trecho:\n«{_preview(preview_text)}»\n\n"
            f"Observações do moderador:\n{notes or '(sem observações)'}\n\n"
            f"Reincidência pode levar a bloqueio do seu acesso social ou da conta. "
            f"Releia os Termos de Uso em {_site_url()}/legal/termos/."
        )
    send_email_notification(
        to_email=email,
        subject=subject,
        body=body,
        use_social=True,
        cta_url=f"{_site_url()}/legal/termos/",
        cta_label="Ver Termos de Uso",
    )


def send_ban_email(
    *, user, action: str, reason: str, terms_clause: str,
    effective_until=None,
) -> None:
    email = (getattr(user, "email", "") or "").strip()
    if not email:
        return

    action_label = {
        "warn": "AVISO",
        "post_block": "Post bloqueado",
        "social_block": "Acesso ao Espaço Social bloqueado",
        "account_block": "Conta NossoTrello bloqueada",
        "idcamim_block": "Conta IDCamim bloqueada",
    }.get(action, action)

    duration = (
        f"até {effective_until:%d/%m/%Y %H:%M}" if effective_until else "por tempo indeterminado"
    )

    body = (
        f"Olá,\n\n"
        f"Sua conta recebeu a seguinte ação: {action_label} ({duration}).\n\n"
        f"Motivo: {reason}\n"
        f"Cláusula violada: {terms_clause or '(não informada)'}\n\n"
        f"Se você acha que isso foi um erro, responda este email. "
        f"Reincidência pode escalar para bloqueio do seu acesso ao IDCamim."
    )
    send_email_notification(
        to_email=email,
        subject=f"[NossoTrello] {action_label}",
        body=body,
        use_social=True,
        cta_url=f"{_site_url()}/legal/termos/",
        cta_label="Ver Termos de Uso",
    )
