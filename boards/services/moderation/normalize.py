"""Normalização anti-leet-speak para casar termos banidos."""
from __future__ import annotations

import re
import unicodedata

# Mapa leet → letra. Não cobre todas as variações exóticas, mas pega
# os ataques mais comuns ("c4m1m", "p0rr4", "5exo", "@nal", ...).
_LEET_MAP = str.maketrans({
    "0": "o", "1": "i", "2": "z", "3": "e", "4": "a",
    "5": "s", "6": "g", "7": "t", "8": "b", "9": "g",
    "@": "a", "$": "s", "!": "i", "|": "i",
})

# Caracteres a remover (separadores comuns usados pra burlar match).
_REMOVE_CHARS = re.compile(r"[\s\-_\.\,\;\:\/\\\'\"\*\+\=\(\)\[\]\{\}<>~`^]+")
# Duplicação de letras ("merrrda" → "merda")
_DUPS = re.compile(r"(.)\1{1,}")


def strip_accents(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def normalize(text: str) -> str:
    """Normaliza texto livre para casar contra termos banidos.

    Operações: lowercase → remove acentos → leet→letra → remove separadores →
    colapsa letras repetidas.

    Exemplos:
      "T3rr0r_da_C4m1m69" → "terordacamimg"  (mas 'terordacamimg' tem 'camim' embutido)
      "Pôrr@!"             → "pora"
      "VAGABUNDOOOO"       → "vagabundo"
    """
    if not text:
        return ""
    s = text.lower()
    s = strip_accents(s)
    s = s.translate(_LEET_MAP)
    s = _REMOVE_CHARS.sub("", s)
    s = _DUPS.sub(r"\1", s)
    return s


def contains(haystack_normalized: str, term_normalized: str) -> bool:
    """True se `term_normalized` aparece como substring em `haystack_normalized`.

    Espera ambos já normalizados via normalize().
    """
    if not term_normalized or not haystack_normalized:
        return False
    return term_normalized in haystack_normalized
