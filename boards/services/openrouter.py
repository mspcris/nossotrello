"""Cliente único de IA do projeto — tudo passa pela OpenRouter.

Decisão do dono (29/09/2026): nada de chave Groq/OpenAI/Anthropic direta.
Chat, embeddings, moderação e geração de imagem saem daqui, com a mesma
chave `OPENROUTER_API_KEY`.

- Chat sempre com `provider.sort = "price"` (o provedor mais barato do modelo).
- Sem fallback para o provedor antigo.
- IDs de modelo no formato da OpenRouter (`openai/gpt-oss-120b`,
  `meta-llama/llama-3.3-70b-instruct`...). IDs antigos da Groq que ainda
  estejam gravados no banco (CamilaConfig.model) são traduzidos por
  `resolve_model()`.
"""
from __future__ import annotations

import logging
import os
import threading

logger = logging.getLogger(__name__)

BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_HEADERS = {"HTTP-Referer": "https://camim.com.br", "X-Title": "nossotrello"}
PROVIDER_CHEAPEST = {"provider": {"sort": "price"}}

# Modelos por uso (conferidos em GET /api/v1/models em 29/09/2026).
MODEL_CHAT_DEFAULT = "meta-llama/llama-3.3-70b-instruct"   # Camila sem config
MODEL_REPORT = "meta-llama/llama-3.3-70b-instruct"         # relatório mensal (era GROQ_MODEL)
MODEL_FOOD_DETECT = "meta-llama/llama-3.3-70b-instruct"    # detector de prato
MODEL_SUMMARY = "anthropic/claude-haiku-4.5"               # resumo de POP (era Claude direto)
MODEL_EMBED = "openai/text-embedding-3-small"              # mesmos vetores de antes (1536d)
MODEL_MODERATION = "openai/gpt-oss-safeguard-20b"          # moderação com política própria
MODEL_IMAGE = "google/gemini-2.5-flash-image"              # foto do prato

# IDs da Groq → IDs da OpenRouter.
_LEGACY_MODELS = {
    "llama-3.3-70b-versatile": "meta-llama/llama-3.3-70b-instruct",
    "llama-3.1-8b-instant": "meta-llama/llama-3.1-8b-instruct",
    # Os dois abaixo não existem mais na OpenRouter; o mais próximo é o 3.3 70B.
    "llama3-70b-8192": "meta-llama/llama-3.3-70b-instruct",
    "mixtral-8x7b-32768": "meta-llama/llama-3.3-70b-instruct",
}


def resolve_model(model: str | None, default: str = MODEL_CHAT_DEFAULT) -> str:
    m = (model or "").strip()
    if not m:
        return default
    return _LEGACY_MODELS.get(m, m)


def api_key() -> str:
    try:
        from django.conf import settings

        return (getattr(settings, "OPENROUTER_API_KEY", "") or "").strip()
    except Exception:  # fora do Django (script solto)
        return (os.getenv("OPENROUTER_API_KEY") or "").strip()


_client = None
_client_lock = threading.Lock()


def get_client():
    """OpenAI SDK apontado para a OpenRouter. None se a chave não estiver configurada."""
    global _client
    key = api_key()
    if not key:
        return None
    if _client is not None:
        return _client
    with _client_lock:
        if _client is None:
            from openai import OpenAI

            _client = OpenAI(
                base_url=BASE_URL,
                api_key=key,
                default_headers=DEFAULT_HEADERS,
                max_retries=1,
            )
    return _client


def chat(messages: list[dict], *, model: str, timeout: float = 30, extra_body: dict | None = None, **kwargs) -> str:
    """Chat completion. Devolve o texto da resposta. Levanta exceção em falha
    (quem chama decide o que fazer — cada uso tem o seu contrato)."""
    client = get_client()
    if client is None:
        raise RuntimeError("OPENROUTER_API_KEY ausente")
    body = dict(PROVIDER_CHEAPEST)
    if extra_body:
        body.update(extra_body)
    resp = client.with_options(timeout=timeout).chat.completions.create(
        model=resolve_model(model),
        messages=messages,
        extra_body=body,
        **kwargs,
    )
    return (resp.choices[0].message.content or "").strip()


def is_configured() -> bool:
    return bool(api_key())
