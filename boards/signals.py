# boards/signals.py
import logging
import random
import re

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Board, CardLog, UserProfile
from .services.pubsub_service import publish_event

logger = logging.getLogger(__name__)

DEFAULT_AVATARS = [
    "avatar1.jpeg",
    "avatar2.png",
    "avatar3.png",
    "avatar4.png",
    "avatar5.png",
    "avatar6.png",
    "avatar7.png",
    "avatar8.png",
    "avatar9.png",
    "avatar10.png",
    "avatar11.png",
]


def _sanitize_handle_base(text: str) -> str:
    """
    Gera uma base segura para handle:
    - usa apenas [a-zA-Z0-9_]
    - cai para 'user' se ficar vazio
    """
    t = (text or "").strip()
    t = re.sub(r"[^a-zA-Z0-9_]+", "", t)
    return t or "user"


def _default_display_name_from_email(email: str) -> str:
    """
    Nome amigável = parte antes do @.
    """
    e = (email or "").strip()
    local = e.split("@", 1)[0] if "@" in e else e
    return (local or "usuario").strip() or "usuario"


def _generate_unique_handle(email: str, *, max_attempts: int = 9999) -> str:
    """
    Handle = 5 primeiros caracteres do email (antes do @) + contagem 01, 02, 03...
    Garantindo unicidade em UserProfile.handle.
    """
    local = _default_display_name_from_email(email)
    base_raw = local[:5]  # regra acordada
    base = _sanitize_handle_base(base_raw)

    # Tenta 01..N; mantém o base dentro de um tamanho seguro
    # (se o campo handle for curto, evitar estourar)
    # Ajuste conservador: reserva até 4 chars para sufixo (ex: 0001) se precisar.
    base = base[:20]

    for i in range(1, max_attempts + 1):
        suffix = f"{i:02d}" if i < 100 else str(i)
        candidate = f"{base}{suffix}"

        # Se ainda assim ficar grande, corta o base e tenta de novo
        if len(candidate) > 24:
            overflow = len(candidate) - 24
            base_cut = base[:-overflow] if overflow < len(base) else "user"
            candidate = f"{base_cut}{suffix}"

        if not UserProfile.objects.filter(handle=candidate).exists():
            return candidate

    # fallback extremo (não deve acontecer)
    return f"{base}01"


# ======================================================================
# PUB/SUB — invalidação de board em tempo real
# ----------------------------------------------------------------------
# Estratégia: toda vez que o objeto Board é salvo, publicamos um evento
# `board.invalidated` no RabbitMQ com a `version` atual. O bridge entrega
# ao grupo `board_<id>` do Channels e o JS no browser recebe o push via
# WebSocket e busca o novo estado — substituindo o polling que rodava
# a cada 60s.
#
# Como os ~40 call-sites de `board.version += 1` sempre chamam
# `board.save()` em seguida, hookar `post_save` dá cobertura total sem
# precisar tocar em cada view.
#
# transaction.on_commit garante que o evento só vai para o broker
# DEPOIS que a transação efetivamente commitou — senão clientes
# poderiam receber notificação de algo que acabou em rollback.
# ======================================================================
@receiver(post_save, sender=Board)
def publish_board_invalidated(sender, instance, **kwargs):
    board_id = instance.id
    version = int(getattr(instance, "version", 0) or 0)

    def _fire():
        try:
            publish_event(
                "board.invalidated",
                board_id=board_id,
                version=version,
            )
        except Exception:  # noqa: BLE001
            logger.debug("publish board.invalidated falhou", exc_info=True)

    try:
        transaction.on_commit(_fire)
    except Exception:  # noqa: BLE001
        # fora de transação — dispara imediatamente
        _fire()


# ======================================================================
# PUB/SUB — atividade de card (log/comentário novo)
# ----------------------------------------------------------------------
# CardLog é criado toda vez que um card ganha um comentário, uma entrada
# de histórico, etc. Publicar aqui substitui o polling
# `/board/<id>/cards/unread-activity/` e `/board/<id>/history/unread-count/`.
#
# Resolve board_id via card.column.board_id de forma preguiçosa. Se a
# lookup falhar (card deletado, inconsistência), ignora silenciosamente.
# ======================================================================
@receiver(post_save, sender=CardLog)
def publish_card_activity(sender, instance, created, **kwargs):
    if not created:
        return

    card_id = instance.card_id
    actor_id = getattr(instance, "actor_id", None)

    def _fire():
        try:
            # resolve board_id on-demand (mantém o signal barato)
            card = instance.card
            board_id = getattr(
                getattr(card, "column", None), "board_id", None
            )
            if not board_id:
                return
            publish_event(
                "card.activity",
                board_id=board_id,
                card_id=card_id,
                actor_id=actor_id,
            )
        except Exception:  # noqa: BLE001
            logger.debug("publish card.activity falhou", exc_info=True)

    try:
        transaction.on_commit(_fire)
    except Exception:  # noqa: BLE001
        _fire()


@receiver(post_save, sender=get_user_model())
def ensure_profile_on_user_create(sender, instance, created, **kwargs):
    if not created:
        return

    # Melhor esforço com atomic + retry simples para corrida de unicidade no handle
    for _ in range(3):
        try:
            with transaction.atomic():
                prof, _created_prof = UserProfile.objects.get_or_create(user=instance)

                changed_fields = []

                # 1) display_name default (antes do @)
                if not (prof.display_name or "").strip():
                    prof.display_name = _default_display_name_from_email(getattr(instance, "email", "") or "")
                    changed_fields.append("display_name")

                # 2) handle default (5 primeiros + 01..)
                if not (prof.handle or "").strip():
                    prof.handle = _generate_unique_handle(getattr(instance, "email", "") or "")
                    changed_fields.append("handle")

                # 3) avatar preset (se não tiver upload nem escolha)
                if not prof.avatar and not prof.avatar_choice:
                    prof.avatar_choice = random.choice(DEFAULT_AVATARS)
                    changed_fields.append("avatar_choice")

                if changed_fields:
                    prof.save(update_fields=changed_fields)

            break

        except IntegrityError:
            # colisão rara de handle em concorrência; tenta de novo
            continue
