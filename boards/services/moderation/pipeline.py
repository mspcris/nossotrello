"""Orquestração das 3 camadas — ponto de entrada das views.

Uso típico (em uma view de criação de conteúdo):

    from boards.services.moderation import check_or_block, ContentBlocked

    try:
        check_or_block(
            text=user_input,
            author=request.user,
            kind=ModerationCase.KIND_SOCIAL_POST,
        )
    except ContentBlocked as exc:
        return HttpResponseBadRequest(exc.user_message)

    # … cria o objeto …
    post = SocialPost.objects.create(...)
    schedule_layer2(post_obj=post, kind=..., text=...)
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Optional

from django.utils import timezone

from .blocklist import scan as blocklist_scan
from .openai_client import classify as openai_classify

logger = logging.getLogger(__name__)


class ContentBlocked(Exception):
    """Camada 1 disse não. View deve devolver HTTP 400 com user_message."""

    def __init__(self, *, user_message: str, terms_clause: str, case_id: Optional[int] = None):
        super().__init__(user_message)
        self.user_message = user_message
        self.terms_clause = terms_clause
        self.case_id = case_id


@dataclass
class _CheckContext:
    text: str
    author: object  # User
    kind: str  # ModerationCase.KIND_*


def check_or_block(
    *,
    text: str,
    author,
    kind: str,
) -> None:
    """Camada 1 síncrona. Levanta ContentBlocked se hit com severity='block'.

    Não cria objeto algum se passar — só registra ModerationCase se houve hit
    (block ou flag). O caller é responsável por criar o conteúdo e chamar
    schedule_layer2() pra disparar a análise contextual em background.
    """
    if not text or not text.strip():
        return  # nada pra checar

    hit = blocklist_scan(text)
    if hit is None:
        return

    if hit.severity == "block":
        # Cria ModerationCase auto_blocked (audit trail mesmo sem objeto criado)
        from boards.models import ModerationCase
        case = ModerationCase.objects.create(
            content_kind=kind,
            object_id=0,  # nenhum objeto criado (bloqueio pré-save)
            author=author,
            subject_text=text[:4000],
            layer1_hit=True,
            layer1_term_id=hit.term_id,
            status=ModerationCase.STATUS_AUTO_BLOCKED,
            decision_at=timezone.now(),
        )
        from .emails import send_block_email
        send_block_email(
            author=author,
            kind=kind,
            terms_clause=hit.terms_clause,
            preview_text=text,
            case_id=case.id,
        )
        raise ContentBlocked(
            user_message=(
                "Sua publicação foi bloqueada por violar a cláusula "
                f"{hit.terms_clause} dos Termos de Uso (categoria: {hit.category}). "
                "Você recebeu um email com mais detalhes."
            ),
            terms_clause=hit.terms_clause,
            case_id=case.id,
        )

    # severity == "flag": deixa criar, mas marca pra revisão humana.
    # O caller chama schedule_layer2 depois de criar o objeto; nada a fazer aqui.


def schedule_layer2(
    *,
    obj,
    kind: str,
    text: str,
    author,
) -> None:
    """Dispara Camada 2 (OpenAI Moderation) em thread daemon.

    `obj` precisa ter `pk` e suportar `moderation_status` se for SocialPost.
    Falha silenciosa — nunca derruba a criação do conteúdo.
    """
    if not text or not text.strip():
        # ainda assim verificamos Camada 1 flag pelo blocklist
        hit = blocklist_scan(text or "")
        if hit is None:
            return

    def _run():
        try:
            _layer2_worker(obj=obj, kind=kind, text=text, author=author)
        except Exception:
            logger.exception("moderation.layer2 worker falhou (obj=%s kind=%s)", getattr(obj, "pk", None), kind)

    threading.Thread(target=_run, daemon=True).start()


def _layer2_worker(*, obj, kind, text, author):
    from boards.models import ModerationCase, SocialPost

    # Re-checa blocklist por consistência (cache pode ter atualizado entre o
    # check síncrono e este worker).
    hit = blocklist_scan(text or "")
    layer1_term_id = hit.term_id if hit else None
    layer1_flag = hit is not None and hit.severity == "flag"

    # Camada 2 — OpenAI
    res = openai_classify(text or "")
    needs_human = (res is not None and res.needs_human) or layer1_flag

    if res is None and not layer1_flag:
        # Sem provedor configurado e sem flag local — nada a fazer.
        return

    case = ModerationCase.objects.create(
        content_kind=kind,
        object_id=getattr(obj, "pk", 0) or 0,
        author=author,
        subject_text=(text or "")[:4000],
        layer1_hit=layer1_flag,
        layer1_term_id=layer1_term_id,
        layer2_provider="openai_moderation" if res else "",
        layer2_scores=(res.scores if res else {}),
        layer2_categories=(res.categories if res else []),
        layer2_flagged=(res.flagged if res else False),
        layer2_at=timezone.now() if res else None,
        status=(
            ModerationCase.STATUS_PENDING_HUMAN if needs_human
            else ModerationCase.STATUS_AUTO_CLEARED
        ),
    )

    if needs_human and isinstance(obj, SocialPost):
        SocialPost.objects.filter(pk=obj.pk).update(
            moderation_status=SocialPost.MOD_PENDING,
            moderation_reason="Sob análise por nossa equipe.",
        )
        from .emails import send_under_review_email
        send_under_review_email(
            author=author,
            kind=kind,
            preview_text=text or "",
            case_id=case.id,
        )
