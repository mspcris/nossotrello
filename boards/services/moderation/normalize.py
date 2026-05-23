"""Normalização anti-leet-speak para casar termos banidos.

Duas variantes:

  normalize_pack(text)  — remove TODOS os separadores. Usado para casar
                          termos como substring (`gozay` casa em
                          `gozaydorme77`). Vulnerável a sobreposição com
                          palavras inocentes em termos curtos.

  normalize_tokens(text) — preserva fronteiras de palavra (separadores
                          viram espaço único). Usado com regex `\\bterm\\b`
                          para termos curtos onde substring quebraria
                          palavras inocentes (`bunda` não pode casar em
                          `abundância`).
"""
from __future__ import annotations

import re
import unicodedata

# Mapa leet → letra. Cobre os ataques mais comuns ("c4m1m", "p0rr4", "@nal").
_LEET_MAP = str.maketrans({
    "0": "o", "1": "i", "2": "z", "3": "e", "4": "a",
    "5": "s", "6": "g", "7": "t", "8": "b", "9": "g",
    "@": "a", "$": "s", "!": "i", "|": "i",
})

# Separadores comuns usados pra burlar match — removidos no pack, viram espaço no tokens.
_SEP_RE = re.compile(r"[\s\-_\.\,\;\:\/\\\'\"\*\+\=\(\)\[\]\{\}<>~`^]+")
# Duplicação de letras ("merrrda" → "merda")
_DUPS = re.compile(r"(.)\1{1,}")


def strip_accents(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _common_pre(text: str) -> str:
    s = text.lower()
    s = strip_accents(s)
    return s.translate(_LEET_MAP)


def normalize_pack(text: str) -> str:
    """Modo substring: tudo junto, sem separador. Casa `gozay` em `@gozay-dorme77`."""
    if not text:
        return ""
    s = _common_pre(text)
    s = _SEP_RE.sub("", s)
    s = _DUPS.sub(r"\1", s)
    return s


def normalize_tokens(text: str) -> str:
    """Modo palavra: separadores viram espaço único, dedup letra por palavra.

    Casa `\\bbunda\\b` em `olha aquela bunda` mas NÃO em `abundância`.
    """
    if not text:
        return ""
    s = _common_pre(text)
    s = _SEP_RE.sub(" ", s).strip()
    # Dedup por palavra pra "vagabunda!" virar "vagabunda" e "voou" virar "vou"
    parts = [_DUPS.sub(r"\1", w) for w in s.split(" ") if w]
    return " ".join(parts)


# Compatibilidade com código antigo que usava `normalize()` (= pack).
normalize = normalize_pack


def contains_substring(haystack_packed: str, term: str) -> bool:
    if not term or not haystack_packed:
        return False
    return term in haystack_packed


_WORD_BOUNDARY_CACHE: dict[str, re.Pattern[str]] = {}


def _word_pattern(term: str) -> re.Pattern[str]:
    pat = _WORD_BOUNDARY_CACHE.get(term)
    if pat is None:
        pat = re.compile(r"\b" + re.escape(term) + r"\b")
        _WORD_BOUNDARY_CACHE[term] = pat
    return pat


def contains_word(haystack_tokens: str, term: str) -> bool:
    if not term or not haystack_tokens:
        return False
    return bool(_word_pattern(term).search(haystack_tokens))


# Compatibilidade com código antigo
def contains(haystack: str, term: str) -> bool:
    return contains_substring(haystack, term)
