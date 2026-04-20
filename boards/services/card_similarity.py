# boards/services/card_similarity.py
"""
Detecção de cards semelhantes via embeddings semânticos.

Pipeline:
  1) Extrai texto do card (título + descrição em texto puro)
  2) Gera embedding via OpenAI text-embedding-3-small (1536d)
  3) Compara por cosseno contra cards visíveis ao usuário
  4) Retorna top-K com score >= threshold

O embedding é persistido em CardEmbedding com hash do conteúdo —
se o texto não mudou, reutiliza; se mudou, regenera.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import threading
from typing import Iterable

import numpy as np
from django.db.models import Q

from boards.models import Board, BoardMembership, Card, CardEmbedding

logger = logging.getLogger(__name__)

EMBED_MODEL = os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-small")
EMBED_DIM = 1536  # text-embedding-3-small

# Limiares de alerta (mesmos que viram cor/intensidade na UI)
THRESHOLD_HIGH = 0.90
THRESHOLD_MED = 0.70
THRESHOLD_LOW = 0.50


# ────────────────────────────────────────────────────────────────
# Texto do card
# ────────────────────────────────────────────────────────────────
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _strip_html(html: str) -> str:
    if not html:
        return ""
    txt = _TAG_RE.sub(" ", html)
    txt = txt.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    return _WS_RE.sub(" ", txt).strip()


def card_text(card: Card) -> str:
    title = (card.title or "").strip()
    desc = _strip_html(card.description or "")
    # cap pra não estourar token budget
    desc = desc[:4000]
    return f"{title}\n\n{desc}".strip()


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ────────────────────────────────────────────────────────────────
# OpenAI client
# ────────────────────────────────────────────────────────────────
_client = None


def _get_client():
    global _client
    if _client is not None:
        return _client
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return None
    try:
        from openai import OpenAI
        _client = OpenAI(api_key=api_key)
        return _client
    except Exception as e:
        logger.warning("OpenAI client indisponível: %s", e)
        return None


def generate_embedding(text: str) -> list[float] | None:
    """
    Retorna embedding (list[float]) ou None se falhar.
    """
    text = (text or "").strip()
    if not text:
        return None
    client = _get_client()
    if client is None:
        return None
    try:
        resp = client.embeddings.create(model=EMBED_MODEL, input=text)
        vec = resp.data[0].embedding
        return list(vec)
    except Exception as e:
        logger.warning("Falha ao gerar embedding: %s", e)
        return None


# ────────────────────────────────────────────────────────────────
# Embed card (cria/atualiza CardEmbedding)
# ────────────────────────────────────────────────────────────────
def embed_card(card: Card, *, force: bool = False) -> CardEmbedding | None:
    text = card_text(card)
    if not text:
        return None

    h = content_hash(text)

    existing = CardEmbedding.objects.filter(card=card).first()
    if existing and not force and existing.content_hash == h and existing.embedding:
        return existing

    vec = generate_embedding(text)
    if not vec:
        return None

    if existing:
        existing.content_hash = h
        existing.embedding = vec
        existing.model = EMBED_MODEL
        existing.save(update_fields=["content_hash", "embedding", "model", "updated_at"])
        return existing

    return CardEmbedding.objects.create(
        card=card,
        content_hash=h,
        embedding=vec,
        model=EMBED_MODEL,
    )


def embed_card_async(card_id: int) -> None:
    """
    Dispara geração de embedding em thread daemon — não bloqueia request.
    Reabre a conexão do Django dentro da thread.
    """
    def _run():
        try:
            from django.db import connection
            connection.close()
            card = Card.all_objects.filter(id=card_id).first()
            if card:
                embed_card(card)
        except Exception as e:
            logger.warning("embed_card_async falhou (card=%s): %s", card_id, e)

    t = threading.Thread(target=_run, daemon=True)
    t.start()


# ────────────────────────────────────────────────────────────────
# Escopo: cards visíveis ao usuário (todos os boards que ele tem acesso)
# ────────────────────────────────────────────────────────────────
def user_visible_board_ids(user) -> set[int]:
    if not user or not getattr(user, "is_authenticated", False):
        return set()

    if getattr(user, "is_superuser", False):
        return set(Board.all_objects.values_list("id", flat=True))

    # boards em que é membro
    member_ids = set(
        BoardMembership.objects.filter(user=user).values_list("board_id", flat=True)
    )
    # boards legados (sem memberships) criados pelo usuário
    created_ids = set(
        Board.all_objects.filter(created_by=user).values_list("id", flat=True)
    )
    return member_ids | created_ids


# ────────────────────────────────────────────────────────────────
# Busca de similares
# ────────────────────────────────────────────────────────────────
def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    na = np.linalg.norm(a)
    nb = np.linalg.norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def find_similar_cards(
    card: Card,
    user,
    *,
    top_k: int = 5,
    min_score: float = THRESHOLD_LOW,
) -> list[dict]:
    """
    Retorna lista de dicts:
        [{"card": Card, "score": float, "status": "active"|"archived"|"deleted"}, ...]
    ordenada por score desc.
    """
    emb = embed_card(card)
    if not emb or not emb.embedding:
        return []

    query_vec = np.array(emb.embedding, dtype=np.float32)

    board_ids = user_visible_board_ids(user)
    if not board_ids:
        return []

    # Busca todos os embeddings de cards em boards visíveis, exceto o próprio
    qs = (
        CardEmbedding.objects
        .select_related("card", "card__column", "card__column__board")
        .filter(card__column__board_id__in=board_ids)
        .exclude(card_id=card.id)
    )

    results = []
    for ce in qs.iterator(chunk_size=500):
        vec = ce.embedding
        if not vec or len(vec) != len(query_vec):
            continue
        score = _cosine(query_vec, np.array(vec, dtype=np.float32))
        if score < min_score:
            continue

        c = ce.card
        if c.is_deleted:
            status = "deleted"
        elif c.is_archived:
            status = "archived"
        else:
            # coluna ou board apagados também contam como "deleted"
            col = c.column
            if getattr(col, "is_deleted", False):
                status = "deleted"
            elif getattr(col.board, "is_deleted", False):
                status = "deleted"
            elif getattr(col.board, "is_archived", False):
                status = "archived"
            else:
                status = "active"

        results.append({"card": c, "score": score, "status": status})

    results.sort(key=lambda r: r["score"], reverse=True)
    return results[:top_k]


def classify_score(score: float) -> str:
    """low | medium | high — usado pela UI pra cor do ícone."""
    if score >= THRESHOLD_HIGH:
        return "high"
    if score >= THRESHOLD_MED:
        return "medium"
    return "low"
