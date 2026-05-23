"""Camada 1 — match determinístico contra BannedTerm."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from django.core.cache import cache

from .normalize import contains, normalize


@dataclass
class BlocklistHit:
    term_id: int
    term: str
    severity: str
    category: str
    terms_clause: str


_CACHE_KEY = "moderation:bannedterms:v1"
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
        .values("id", "term", "severity", "category", "terms_clause")
    )
    cache.set(_CACHE_KEY, rows, _CACHE_TTL)
    return rows


def invalidate_cache() -> None:
    cache.delete(_CACHE_KEY)


def scan(text: str) -> Optional[BlocklistHit]:
    """Retorna o primeiro BlocklistHit ou None.

    Prioriza severity='block' sobre 'flag' (se um termo block aparece, esse vence).
    """
    if not text:
        return None
    normalized = normalize(text)
    if not normalized:
        return None

    flag_hit: Optional[BlocklistHit] = None
    for row in _load_terms():
        if not contains(normalized, row["term"]):
            continue
        hit = BlocklistHit(
            term_id=row["id"],
            term=row["term"],
            severity=row["severity"],
            category=row["category"],
            terms_clause=row["terms_clause"] or "4.4",
        )
        if hit.severity == "block":
            return hit
        if flag_hit is None:
            flag_hit = hit
    return flag_hit
