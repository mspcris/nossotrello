"""Tarefas em segundo plano (Celery). Ver nossotrello/celery.py e boards/services/jobs.py.

Regra: a tarefa é um embrulho fino. O trabalho de verdade mora numa função comum
(importada aqui dentro, para não criar ciclo de import), que também serve de
caminho de reserva quando a fila está fora do ar.
"""
from __future__ import annotations

import logging
import re

from celery import shared_task
from django.core.cache import cache
from django.utils import timezone

logger = logging.getLogger(__name__)


def _backoff(retries: int, base: int = 30, cap: int = 1800) -> int:
    """Espera crescente: base, 2x, 4x... até o teto."""
    return min(cap, base * (2 ** max(0, int(retries))))


# ============================================================
# E-MAIL
# ============================================================
@shared_task(bind=True, name="boards.tasks.deliver_email", max_retries=5, acks_late=True)
def deliver_email(self, payload):
    from boards.services.queued_email import deliver_now

    try:
        deliver_now(payload)
    except Exception as exc:
        if self.request.retries >= self.max_retries:
            logger.error(
                "email: desisti após %s tentativas to=%s assunto=%r erro=%s",
                self.request.retries + 1, payload.get("to"), payload.get("subject"), exc,
            )
            raise
        raise self.retry(exc=exc, countdown=_backoff(self.request.retries, base=30))


# ============================================================
# WHATSAPP (Evolution API)
# ============================================================
_PERMANENT_HTTP = re.compile(r"HTTP 4(?!08|29)\d\d")


def _whatsapp_is_permanent(exc) -> bool:
    """4xx (menos 408/429) = número inexistente, payload inválido... repetir não adianta."""
    msg = str(exc)
    return bool(_PERMANENT_HTTP.search(msg)) or "Número inválido" in msg or "vazio" in msg


@shared_task(bind=True, name="boards.tasks.send_whatsapp_task", max_retries=4, acks_late=True)
def send_whatsapp_task(self, user_id, phone_digits, body):
    from boards.services.notifications import send_whatsapp_now

    try:
        send_whatsapp_now(phone_digits=phone_digits, body=body)
    except Exception as exc:
        if _whatsapp_is_permanent(exc):
            logger.warning("evolution: falha definitiva (sem nova tentativa) user_id=%s: %s", user_id, exc)
            return
        if self.request.retries >= self.max_retries:
            logger.error("evolution: desisti após %s tentativas user_id=%s: %s", self.request.retries + 1, user_id, exc)
            return
        raise self.retry(exc=exc, countdown=_backoff(self.request.retries, base=20, cap=900))


# ============================================================
# NOTIFICAÇÕES DE SEGUIDORES (buffer consolidado pelo flush_notifications)
# ============================================================
@shared_task(bind=True, name="boards.tasks.card_notifications", max_retries=3, acks_late=True)
def card_notifications(self, card_id, actor_id, actor_name, event_text):
    from boards.views.helpers import create_notification_buffers

    try:
        create_notification_buffers(card_id, actor_id, actor_name, event_text)
    except Exception as exc:
        if self.request.retries >= self.max_retries:
            logger.error("card_notifications: desisti card=%s erro=%s", card_id, exc)
            return
        raise self.retry(exc=exc, countdown=_backoff(self.request.retries, base=10, cap=300))


# ============================================================
# TRABALHO PESADO (fila "media"): vídeo, imagem por IA, moderação, embeddings
# Sem retry por exceção (ffmpeg/IA falham de forma determinística); o que a fila
# garante aqui é sair do processo web e sobreviver a deploy (acks_late).
# ============================================================
@shared_task(name="boards.tasks.video_playable_build", acks_late=True)
def video_playable_build(source_id):
    from boards.services.video_playable import run_playable_job

    run_playable_job(source_id)


@shared_task(name="boards.tasks.video_compress_post", acks_late=True)
def video_compress_post(post_id):
    from boards.services.video_compress import run_compress_job

    run_compress_job(post_id)


@shared_task(name="boards.tasks.food_image_post", acks_late=True)
def food_image_post(post_id):
    from boards.services.food_image import run_food_image_job

    run_food_image_job(post_id)


@shared_task(name="boards.tasks.embed_card", acks_late=True)
def embed_card(card_id):
    from boards.services.card_similarity import run_embed_job

    run_embed_job(card_id)


@shared_task(name="boards.tasks.moderation_layer2", acks_late=True)
def moderation_layer2(model_label, pk, kind, text, author_id):
    from boards.services.moderation.pipeline import run_layer2_job

    run_layer2_job(model_label, pk, kind, text, author_id)


# ============================================================
# QUADRO — fila ordenada (board_ops): UM consumidor, operações na ordem do clique
# ============================================================
MOVE_MAX_RETRIES = 2            # 3 tentativas no total
MOVE_RETRY_DELAYS = (2, 6)      # segundos


def _attempts_key(op_id) -> str:
    return f"nt:move:attempts:{op_id}"


def _record_attempt(op_id, attempt: int, error: str) -> list:
    key = _attempts_key(op_id)
    try:
        items = cache.get(key) or []
        items.append({
            "n": attempt,
            "at": timezone.localtime().strftime("%d/%m/%Y %H:%M:%S"),
            "error": (error or "")[:300],
        })
        cache.set(key, items, 3600)
        return items
    except Exception:
        return [{"n": attempt, "at": "", "error": (error or "")[:300]}]


@shared_task(bind=True, name="boards.tasks.board_ops_heartbeat", ignore_result=True)
def board_ops_heartbeat(self):
    from boards.services.jobs import mark_board_ops_alive

    mark_board_ops_alive()


@shared_task(bind=True, name="boards.tasks.apply_card_move", max_retries=MOVE_MAX_RETRIES, acks_late=True)
def apply_card_move(self, op_id, card_id, new_column_id, new_position, user_id, requested_at):
    """Grava o mover-card que a tela já mostrou. 3 tentativas; se nenhuma der
    certo, avisa o usuário na tela (evento card.move.failed) e por e-mail."""
    from django.contrib.auth import get_user_model
    from django.db import transaction

    from boards.services.card_move_feedback import notify_move_failed
    from boards.views.cards import CardMoveRejected, is_move_superseded, perform_card_move

    attempt = self.request.retries + 1
    try:
        if is_move_superseded(card_id, requested_at):
            logger.info("move: op=%s card=%s ignorado (há um movimento mais novo do mesmo card)", op_id, card_id)
            return "superseded"
        user = get_user_model().objects.select_related("profile").get(pk=user_id)
        with transaction.atomic():
            perform_card_move(
                user=user,
                card_id=card_id,
                new_column_id=new_column_id,
                new_position=new_position,
            )
        return "ok"
    except CardMoveRejected as exc:
        # permissão negada / card ou coluna sumiu: repetir não muda o resultado
        attempts = _record_attempt(op_id, attempt, str(exc))
        notify_move_failed(op_id=op_id, card_id=card_id, user_id=user_id, attempts=attempts, reason=str(exc))
        return "rejected"
    except Exception as exc:
        attempts = _record_attempt(op_id, attempt, f"{type(exc).__name__}: {exc}")
        logger.warning("move: op=%s card=%s tentativa %s falhou: %s", op_id, card_id, attempt, exc)
        if self.request.retries >= self.max_retries:
            notify_move_failed(op_id=op_id, card_id=card_id, user_id=user_id, attempts=attempts, reason="")
            raise
        delay = MOVE_RETRY_DELAYS[min(self.request.retries, len(MOVE_RETRY_DELAYS) - 1)]
        raise self.retry(exc=exc, countdown=delay)


# ============================================================
# PERIÓDICAS (celery beat) — substituem o laço de shell do antigo "scheduler"
# ============================================================
@shared_task(bind=True, name="boards.tasks.run_management_command", ignore_result=True)
def run_management_command(self, command_name, *args):
    """Roda um manage.py <comando> com trava: uma execução não atropela a anterior."""
    from django.core.management import call_command

    lock = f"nt:jobs:cmd:{command_name}"
    if not cache.add(lock, "1", 1500):
        logger.info("periodic: %s ainda rodando — pulei esta rodada", command_name)
        return
    started = timezone.now()
    try:
        call_command(command_name, *args)
        logger.info("periodic: %s ok em %.1fs", command_name, (timezone.now() - started).total_seconds())
    except Exception:
        logger.exception("periodic: %s falhou", command_name)
    finally:
        try:
            cache.delete(lock)
        except Exception:
            pass
