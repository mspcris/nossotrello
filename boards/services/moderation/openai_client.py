"""Camada 2 — classificação de moderação pela OpenRouter.

Até 29/09/2026 era a OpenAI Moderation API (omni-moderation-latest). A
OpenRouter não tem endpoint de moderação, então a classificação é feita por
chat com o gpt-oss-safeguard-20b (modelo de segurança que segue política
escrita) e a política abaixo pede as MESMAS 13 categorias da OpenAI, com
score 0-1. O contrato de `classify()` (ModerationResult) não mudou.

Llama Guard 4 foi testado e descartado: não tem categoria de assédio/insulto
e deixou passar "você é um idiota incompetente" e "vou te encher de porrada".
O safeguard acertou 10 de 10 frases de teste em português (inclusive as
hipérboles "vou matar esse relatório", "me deixou louca").
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

_TIMEOUT = 30  # segundos (roda em background, na fila "media")
PROVIDER_LABEL = "openrouter_safeguard"

# Limiar acima do qual mandamos pra revisão humana mesmo que `flagged=False`.
# flagged = score >= 0.5; usamos 0.3 pra capturar borderline.
_HUMAN_REVIEW_THRESHOLD = 0.30

CATEGORIES = (
    "harassment", "harassment/threatening", "hate", "hate/threatening",
    "violence", "violence/graphic", "self-harm", "self-harm/intent",
    "self-harm/instructions", "sexual", "sexual/minors", "illicit",
    "illicit/violent",
)

_POLICY = (
    "Você é o classificador de moderação de uma rede social interna de trabalho "
    "(funcionários de uma rede de clínicas no Brasil). Textos em português do Brasil, "
    "com gírias, ironia e exageros comuns (\"vou matar esse relatório\", \"me deixou "
    "louca\", \"kkkk\") — isso NÃO é violação.\n\n"
    "Avalie o texto do usuário nestas categorias (mesmos nomes da OpenAI Moderation):\n"
    "- harassment: insulto, humilhação, xingamento ou hostilidade dirigida a uma pessoa.\n"
    "- harassment/threatening: assédio com ameaça de dano a alguém.\n"
    "- hate: ataque ou desprezo a um grupo por origem, raça, etnia, região, religião, "
    "gênero, orientação sexual, deficiência etc.\n"
    "- hate/threatening: discurso de ódio com ameaça ou incitação à violência contra o grupo.\n"
    "- violence: ameaça ou apologia de violência física real.\n"
    "- violence/graphic: descrição gráfica de ferimentos, sangue, morte.\n"
    "- self-harm: menção de autolesão ou suicídio da própria pessoa.\n"
    "- self-harm/intent: intenção declarada de se ferir ou se matar.\n"
    "- self-harm/instructions: instruções de como se ferir.\n"
    "- sexual: conteúdo sexual, assédio sexual, pedido de nudez.\n"
    "- sexual/minors: qualquer conteúdo sexual envolvendo menores.\n"
    "- illicit: pedido ou instrução para crime (drogas, fraude, armas).\n"
    "- illicit/violent: instrução para crime violento.\n\n"
    "Para cada categoria dê um score de 0.0 a 1.0 (probabilidade de violação). Uma "
    "categoria é true quando o score >= 0.5. flagged = true se qualquer categoria for true.\n\n"
    "Responda SOMENTE um JSON neste formato exato, com as 13 categorias:\n"
    '{"flagged": false, "categories": {"harassment": false, ...}, '
    '"category_scores": {"harassment": 0.0, ...}}'
)


@dataclass
class ModerationResult:
    flagged: bool
    scores: dict
    categories: list[str]
    needs_human: bool


def _parse(content: str) -> dict:
    t = (content or "").strip()
    try:
        return json.loads(t)
    except Exception:
        m = re.search(r"\{.*\}", t, re.S)
        return json.loads(m.group(0)) if m else {}


def classify(text: str) -> Optional[ModerationResult]:
    """Classifica pela OpenRouter. Retorna None se não configurado ou erro."""
    if not text or not text.strip():
        return None
    from boards.services import openrouter

    if not openrouter.is_configured():
        return None

    try:
        content = openrouter.chat(
            [
                {"role": "system", "content": _POLICY},
                {"role": "user", "content": text[:4000]},
            ],
            model=openrouter.MODEL_MODERATION,
            temperature=0,
            max_tokens=1500,
            response_format={"type": "json_object"},
            timeout=_TIMEOUT,
            extra_body={"reasoning": {"effort": "low"}},
        )
        data = _parse(content)
    except Exception as e:
        logger.warning("Moderação (OpenRouter) falhou: %s", e)
        return None

    raw_scores = data.get("category_scores") if isinstance(data, dict) else None
    if not isinstance(raw_scores, dict) or not raw_scores:
        logger.warning("Moderação (OpenRouter): resposta sem category_scores: %r", (content or "")[:200])
        return None

    scores = {}
    for k in CATEGORIES:
        try:
            scores[k] = max(0.0, min(1.0, float(raw_scores.get(k, 0) or 0)))
        except (TypeError, ValueError):
            scores[k] = 0.0
    # Categoria é "true" pelo score (>= 0.5) — não confiamos só no booleano do modelo.
    cats_dict = data.get("categories") if isinstance(data.get("categories"), dict) else {}
    flagged_categories = [k for k in CATEGORIES if scores[k] >= 0.5 or cats_dict.get(k) is True]
    flagged = bool(flagged_categories) or data.get("flagged") is True

    needs_human = flagged or any(v >= _HUMAN_REVIEW_THRESHOLD for v in scores.values())

    return ModerationResult(
        flagged=flagged,
        scores=scores,
        categories=flagged_categories,
        needs_human=needs_human,
    )
