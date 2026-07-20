"""Atualizar a descrição de um card a partir de OUTRO sistema, com o mesmo
registro de "Antes/Depois" que a interface produz.

O HESK é dono do texto de abertura do chamado; quando alguém edita a descrição
por lá, o card precisa acompanhar. Trocar `card.description` no banco não basta —
a interface, ao alterar a descrição, registra no feed quem alterou, o texto
anterior e o novo. É esse registro que dá rastreabilidade ao dev, e é ele que
precisa continuar existindo quando a alteração vem de fora.

O `api_card_update` do api_mobile já aceita `description`, mas grava em silêncio:
nenhuma linha no feed. Por isso este serviço, e não aquele endpoint.
"""
import logging

from django.db import transaction
from django.utils.html import escape, strip_tags

logger = logging.getLogger(__name__)


def _resumir(html, limite=220):
    """Texto puro e encurtado — o feed mostra um resumo, não o HTML inteiro.
    Mesma regra do `_summarize_html` usado pela view web."""
    import re
    txt = re.sub(r"\s+", " ", strip_tags(html or "")).strip()
    return (txt[:limite].rstrip() + "…") if len(txt) > limite else txt


@transaction.atomic
def atualizar_descricao(*, card, descricao, actor, request=None):
    """Troca a descrição do card e registra Antes/Depois no feed.

    Devolve True se mudou algo. Idempotente: descrição igual não gera log — senão
    cada sincronização encheria o feed de ruído."""
    from boards.views.helpers import _log_card

    antes = card.description or ""
    depois = descricao or ""
    if antes.strip() == depois.strip():
        return False

    card.description = depois
    card.save(update_fields=["description"])

    if request is not None:
        _log_card(
            card, request,
            (
                f"<p><strong>{escape(_nome(actor))}</strong> alterou a descrição.</p>"
                "<div style='margin-top:6px'>"
                "<div style='font-size:12px;opacity:.75;margin-bottom:4px'>Antes:</div>"
                "<div style='padding:10px;border:1px solid rgba(15,23,42,0.10);"
                "border-radius:10px;background:rgba(255,255,255,0.35)'>"
                f"<em>{escape(_resumir(antes))}</em></div>"
                "</div>"
                "<div style='margin-top:10px'>"
                "<div style='font-size:12px;opacity:.75;margin-bottom:4px'>Depois:</div>"
                "<div style='padding:10px;border:1px solid rgba(15,23,42,0.10);"
                "border-radius:10px;background:rgba(255,255,255,0.35)'>"
                f"<strong>{escape(_resumir(depois))}</strong></div>"
                "</div>"
            ),
        )

    try:
        board = card.column.board
        board.version = (board.version or 0) + 1
        board.save(update_fields=["version"])
    except Exception:
        logger.debug("atualizar_descricao: bump de versao falhou", exc_info=True)
    return True


def _nome(user):
    """Nome de exibição do usuário (perfil > nome completo > login)."""
    if not user or not getattr(user, "id", None):
        return "Sistema"
    prof = getattr(user, "profile", None)
    return ((getattr(prof, "display_name", "") or "").strip()
            or user.get_full_name() or user.get_username() or "Sistema")
