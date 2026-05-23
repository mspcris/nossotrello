"""Camada 2 — chamada à OpenAI Moderation API.

API gratuita: https://platform.openai.com/docs/api-reference/moderations

Resposta:
  {
    "id": "modr-...",
    "model": "omni-moderation-latest",
    "results": [{
      "flagged": true,
      "categories": {"hate": false, "harassment": true, ...},
      "category_scores": {"hate": 0.001, "harassment": 0.93, ...}
    }]
  }
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

_API_URL = "https://api.openai.com/v1/moderations"
_MODEL = "omni-moderation-latest"
_TIMEOUT = 10  # segundos

# Limiar acima do qual mandamos pra revisão humana mesmo que `flagged=False`.
# A OpenAI marca como flagged scores >~0.5; usamos 0.3 pra capturar borderline.
_HUMAN_REVIEW_THRESHOLD = 0.30


@dataclass
class ModerationResult:
    flagged: bool
    scores: dict
    categories: list[str]
    needs_human: bool


def _api_key() -> str:
    return (getattr(settings, "OPENAI_API_KEY", "") or "").strip()


def classify(text: str) -> Optional[ModerationResult]:
    """Chama OpenAI Moderation. Retorna None se não configurado ou erro."""
    if not text or not text.strip():
        return None
    key = _api_key()
    if not key:
        return None

    try:
        resp = requests.post(
            _API_URL,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={"model": _MODEL, "input": text[:4000]},  # OpenAI aceita até 32k; cortamos por segurança
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.warning("OpenAI Moderation falhou: %s", e)
        return None

    data = resp.json() or {}
    results = data.get("results") or []
    if not results:
        return None
    r0 = results[0]
    scores = r0.get("category_scores") or {}
    cats_dict = r0.get("categories") or {}
    flagged = bool(r0.get("flagged"))
    flagged_categories = [k for k, v in cats_dict.items() if v]

    # Promove a revisão humana se algum score borderline (não-flagged mas alto).
    needs_human = flagged or any(
        (isinstance(v, (int, float)) and v >= _HUMAN_REVIEW_THRESHOLD)
        for v in scores.values()
    )

    return ModerationResult(
        flagged=flagged,
        scores=scores,
        categories=flagged_categories,
        needs_human=needs_human,
    )
