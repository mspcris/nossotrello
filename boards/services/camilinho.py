"""Mascote Camilinho — mapeamento mood→imagens e helpers.

Cada mood tem N variantes em boards/static/boards/images/camilinho/<slug>_v<n>.png.
Ao postar uma emoção a view sorteia 1..N e grava em SocialPost.camilinho_variant
pra renderizar sempre a mesma imagem (estável por post).

A pasta dos PNGs é boards/static/boards/images/camilinho/.
"""
from __future__ import annotations

import random

from django.templatetags.static import static


# Quantas variantes existem por mood. Se um dia adicionar mais imagens,
# basta bumpar aqui — não precisa de migration.
VARIANTS_PER_MOOD = 3

# DB mood code → slug do arquivo na pasta static. Vide MOOD_CHOICES em
# DailyCheckIn. A pasta usa slug em PT pra ficar legível no diretório.
MOOD_TO_SLUG = {
    "excited": "animado",
    "happy": "bem",
    "calm": "tranquilo",
    "neutral": "normal",
    "tired": "cansado",
    "stressed": "estressado",
    "sick": "indisposto",
    "sad": "triste",
    "down": "desanimado",
    "anxious": "ansioso",
    "angry": "com_raiva",
    "inlove": "apaixonado",
    "grateful": "grato",
}


def pick_variant(mood_code: str) -> int:
    """Sorteia uma variante 1..N pra esse mood. Retorna 0 se mood desconhecido."""
    if mood_code not in MOOD_TO_SLUG:
        return 0
    return random.randint(1, VARIANTS_PER_MOOD)


def image_url(mood_code: str, variant: int) -> str:
    """Static URL pra imagem do Camilinho desse mood+variant. '' se inválido.
    Mantido pra compat — atualmente usamos sprite_class (vide abaixo)."""
    slug = MOOD_TO_SLUG.get(mood_code)
    if not slug or not (1 <= variant <= VARIANTS_PER_MOOD):
        return ""
    return static(f"boards/images/camilinho/{slug}_v{variant}.png")


def sprite_class(mood_code: str, variant: int) -> str:
    """CSS class pra renderizar o Camilinho via sprite WebP único.
    Ex: 'cm-sprite cm-sprite-excited-1' → div pega o frame correto do sprite.
    '' se inválido."""
    slug = MOOD_TO_SLUG.get(mood_code)
    if not slug or not (1 <= variant <= VARIANTS_PER_MOOD):
        return ""
    return f"cm-sprite cm-sprite-{slug}-{variant}"


def animation_class(mood_code: str) -> str:
    """Classe CSS opcional pra animação por mood (ver camilinho.css).
    Devolve string vazia se mood não tem animação custom."""
    return {
        "excited": "cm-anim-bounce",
        "happy": "cm-anim-bob",
        "calm": "cm-anim-breathe",
        "tired": "cm-anim-sway",
        "stressed": "cm-anim-shake-fast",
        "sick": "cm-anim-sway",
        "sad": "cm-anim-droop",
        "down": "cm-anim-droop",
        "anxious": "cm-anim-jitter",
        "angry": "cm-anim-shake-hard",
        "inlove": "cm-anim-pulse",
        "grateful": "cm-anim-bow",
    }.get(mood_code, "")
