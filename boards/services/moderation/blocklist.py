"""Camada 1 — match determinístico contra BannedTerm.

Suporta 2 modos de match por termo (campo `match_mode` em BannedTerm):
  - substring: casa `gozay` em `gozaydorme77` (default — pega ataques de
    concatenação)
  - word:      casa `\\bbunda\\b` em "olha aquela bunda" mas NÃO em
    "abundância" (usar pra termos curtos que colidem com palavras normais)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from django.core.cache import cache

from .normalize import (
    contains_substring,
    contains_word,
    normalize_pack,
    normalize_tokens,
)


@dataclass
class BlocklistHit:
    term_id: int
    term: str
    severity: str
    category: str
    terms_clause: str


_CACHE_KEY = "moderation:bannedterms:v2"
_CACHE_TTL = 60  # 1 minuto — suficiente pro admin ver mudanças logo


def _load_terms() -> list[dict]:
    """Carrega termos ativos. Cacheado por _CACHE_TTL pra evitar query em cada save."""
    cached = cache.get(_CACHE_KEY)
    if cached is not None:
        return cached

    from boards.models import BannedTerm
    rows = list(
        BannedTerm.objects
        .filter(active=True)
        .values("id", "term", "severity", "category", "terms_clause", "match_mode")
    )
    cache.set(_CACHE_KEY, rows, _CACHE_TTL)
    return rows


def invalidate_cache() -> None:
    cache.delete(_CACHE_KEY)


def scan(text: str) -> Optional[BlocklistHit]:
    """Retorna o primeiro BlocklistHit ou None.

    Prioriza severity='block' sobre 'flag'. Pré-normaliza nos 2 modos uma vez
    só por chamada.
    """
    if not text:
        return None
    packed = normalize_pack(text)
    tokens = normalize_tokens(text)
    if not packed and not tokens:
        return None

    flag_hit: Optional[BlocklistHit] = None
    for row in _load_terms():
        term = row["term"]
        mode = row.get("match_mode") or "substring"
        if mode == "word":
            matched = contains_word(tokens, term)
        else:
            matched = contains_substring(packed, term)
        if not matched:
            continue
        hit = BlocklistHit(
            term_id=row["id"],
            term=term,
            severity=row["severity"],
            category=row["category"],
            terms_clause=row["terms_clause"] or "4.4",
        )
        if hit.severity == "block":
            return hit
        if flag_hit is None:
            flag_hit = hit
    return flag_hit
