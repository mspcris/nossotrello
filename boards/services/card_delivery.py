"""Mover um card para uma coluna e marcá-lo como Entregue, em UMA operação.

Existe para servidor-a-servidor: o HESK, ao resolver um chamado, precisa levar o
card ligado a ele para a coluna de "Testado ok" do dev e marcar a entrega. O
requisito é executar TUDO o que a interface executaria — automações da coluna,
feed, seguidores, e-mail/WhatsApp de entrega — e não apenas carimbar os campos no
banco. Por isso isto vive em Python e reaproveita os mesmos helpers da view web
(`run_for`, `_log_card`, `mark_card_delivered`, `notify_delivery`): escrever
direto no Postgres deixaria de fora justamente os efeitos, que é o que importa.

A duplicação em relação a `boards.views.cards.move_card` se restringe à
reindexação de `position` (mecânica). Todo efeito colateral é delegado aos
helpers compartilhados, para não haver duas verdades sobre o que é "entregar".
"""
import logging

from django.db import transaction
from django.db.models import F
from django.utils import timezone
from django.utils.html import escape

logger = logging.getLogger(__name__)


@transaction.atomic
def mover_e_entregar(*, card, coluna_destino, actor, request=None, entregar=True):
    """Move `card` para `coluna_destino` e (opcionalmente) marca como Entregue.

    `actor` é o usuário a quem a ação é atribuída (aparece no feed e nas
    notificações). `request` só é usado pelo `_log_card` para descobrir o autor —
    quando vier de uma API, passe a própria request do DRF.

    Idempotente nas duas pontas: card já na coluna não é movido de novo, card já
    entregue não gera segundo log nem segunda notificação.

    Retorna um dict com o que de fato aconteceu."""
    from boards.models import Card, CardFollow, CardMoveHistory, ColumnFollow
    from boards.services.column_automation import run_count_triggers, run_for
    from boards.services.notifications import mark_card_delivered, notify_delivery
    from boards.views.helpers import _log_card

    resultado = {"movido": False, "entregue": False, "erros": []}

    coluna_origem = card.column
    board_destino = coluna_destino.board
    trocou_coluna = coluna_origem.id != coluna_destino.id

    if trocou_coluna:
        # --- reindexa a coluna de origem (mesma mecânica do move_card) ---
        for i, c in enumerate(coluna_origem.cards.exclude(id=card.id).order_by("position")):
            if int(c.position or 0) != i:
                c.position = i
                c.save(update_fields=["position"])

        card.column = coluna_destino
        card.save(update_fields=["column"])

        # --- auto-follow: quem segue a coluna destino passa a seguir o card ---
        try:
            ids = list(ColumnFollow.objects.filter(
                column=coluna_destino, include_new=True).values_list("user_id", flat=True))
            if ids:
                CardFollow.objects.bulk_create(
                    [CardFollow(card_id=card.id, user_id=uid) for uid in ids],
                    ignore_conflicts=True)
        except Exception:
            logger.debug("mover_e_entregar: auto-follow falhou", exc_info=True)

        # --- posiciona no TOPO da coluna destino e zera o cronômetro de parada ---
        # No fim ele ficaria invisível: "Testado ok" é coluna de arquivo, com
        # centenas de cards acumulados. O que acabou de ser aprovado é
        # justamente o que alguém pode querer conferir.
        #
        # Exceção: CARD CONTADOR (counter_mode <> "") mora no alto da coluna e não
        # pode ser empurrado para baixo. O card entregue entra logo DEPOIS do
        # último contador — nunca em primeiro. Usa a MAIOR posição de contador em
        # vez de contar o bloco do topo porque nem sempre eles começam na posição
        # 0: há coluna com o contador na 1, atrás de um card comum.
        _pos_contadores = [
            p for p, m in (coluna_destino.cards.exclude(id=card.id)
                           .values_list("position", "counter_mode"))
            if (m or "").strip()]
        pos_destino = (max(_pos_contadores) + 1) if _pos_contadores else 0
        Card.objects.filter(column=coluna_destino, position__gte=pos_destino).exclude(
            id=card.id).update(position=F("position") + 1)
        card.position = pos_destino
        card._placed_at = card.column_since   # a automação notify_placer lê isto
        card.column_since = timezone.now()
        card.save(update_fields=["position", "column_since"])

        board_destino.version = (board_destino.version or 0) + 1
        board_destino.save(update_fields=["version"])

        # --- automações: mesma ordem da interface ('leave' antes do placer) ---
        try:
            run_for(card, "leave", coluna_origem, actor=actor)
            card.column_entered_by = actor
            card.save(update_fields=["column_entered_by"])
            run_for(card, "enter", coluna_destino, actor=actor)
            run_count_triggers(coluna_origem, actor=actor)
            run_count_triggers(coluna_destino, actor=actor)
        except Exception:
            logger.exception("mover_e_entregar: automacao falhou card=%s", card.id)
            resultado["erros"].append("automacao")

        try:
            CardMoveHistory.objects.create(
                user=actor, from_column=coluna_origem, to_column=coluna_destino,
                from_board=coluna_origem.board, to_board=board_destino)
        except Exception:
            logger.debug("mover_e_entregar: CardMoveHistory falhou", exc_info=True)

        if request is not None:
            _log_card(card, request,
                      f"<p><strong>{escape(_nome(actor))}</strong> moveu este card de "
                      f"<strong>{escape(coluna_origem.name)}</strong> para "
                      f"<strong>{escape(coluna_destino.name)}</strong>.</p>")
        resultado["movido"] = True

    # --- entrega: só se ainda não estiver entregue (não duplica notificação) ---
    if entregar and not getattr(card, "is_delivered", False):
        mark_card_delivered(card=card, actor=actor)
        if request is not None:
            _log_card(card, request,
                      f"<p><strong>{escape(_nome(actor))}</strong> marcou este card como "
                      f"<strong>Entregue</strong>.</p>")
        try:
            notify_delivery(card=card, actor=actor)
        except Exception:
            logger.exception("mover_e_entregar: notify_delivery falhou card=%s", card.id)
            resultado["erros"].append("notify_delivery")
        resultado["entregue"] = True

    return resultado


def _nome(user):
    """Nome de exibição do usuário (perfil > nome completo > login)."""
    if not user or not getattr(user, "id", None):
        return "Sistema"
    prof = getattr(user, "profile", None)
    return ((getattr(prof, "display_name", "") or "").strip()
            or user.get_full_name() or user.get_username() or "Sistema")
