"""Detecção de comida em posts de texto + geração de foto do prato via DALL-E.

Fluxo (chamado em background por process_food_post):
    1. detect_dish(text) usa Groq pra decidir se o texto é uma menção a uma
       comida CONHECIDA com confiança ≥ 0.95, e retornar o nome canônico
       do prato (ex: "Strogonoff de carne"). Sem foto → None.
    2. Checa cota (1/dia/usuário). Já bateu → desiste.
    3. generate_dish_image(dish_name) usa DALL-E 3 pra criar foto do prato.
    4. Salva os bytes em SocialPost.photo via compress_image, marca
       ai_food_dish e dispara save.

Tudo "best-effort": qualquer falha (timeout, key faltando, post excluído)
loga em warning e termina sem propagar.
"""

import base64
import json
import logging
import os
import re
import threading

import requests as http_requests
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.utils import timezone


logger = logging.getLogger(__name__)

_GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
_GROQ_MODEL = "llama-3.3-70b-versatile"

_OPENAI_IMAGE_URL = "https://api.openai.com/v1/images/generations"
# gpt-image-1 é o modelo de imagem atual da OpenAI (sucessor de DALL-E 3).
# Retorna b64_json por padrão (diferente do DALL-E 3 que devolvia URL).
_OPENAI_IMAGE_MODEL = "gpt-image-1"

_CONFIDENCE_THRESHOLD = 0.95

_DETECTOR_SYSTEM_PROMPT = (
    "Você é um detector de pratos de comida em posts curtos de rede social. "
    "Receba o texto e responda APENAS um JSON com este formato exato:\n"
    '{"is_food": true|false, "confidence": 0.0-1.0, "dish_name": "Nome canônico do prato em português"}\n'
    "Regras:\n"
    "- is_food=true SÓ se o texto menciona claramente um prato de comida REAL e CONHECIDO "
    "(ex: Strogonoff, Feijoada, Lasanha, Pizza Margherita, Tapioca, Bobó de camarão, Sushi, "
    "Hambúrguer, Macarrão à bolonhesa).\n"
    "- confidence ≥ 0.95 SÓ quando você tem certeza ABSOLUTA de que é um prato específico "
    "e conhecido pelo nome dado. Frases vagas como 'comi um lanche', 'almoço gostoso', "
    "'um docinho' devem ter confidence baixa.\n"
    "- dish_name deve ser o nome canônico curto (1-4 palavras), sem emoji, sem reticências, "
    "sem adjetivos do autor ('delicioso', 'maravilhoso'). Bebidas e ingredientes soltos "
    "(arroz puro, batata, leite) NÃO contam como prato → is_food=false.\n"
    "- Não invente comidas. Se em dúvida, is_food=false.\n"
    "- Retorne APENAS o JSON, nada mais."
)


def _strip_json(text: str) -> str:
    """Remove cercas de markdown ``` que LLMs gostam de adicionar."""
    t = (text or "").strip()
    t = re.sub(r"^```(?:json)?\s*", "", t)
    t = re.sub(r"\s*```$", "", t)
    return t.strip()


def detect_dish(text: str) -> str:
    """Retorna o nome canônico do prato se text descreve uma comida conhecida
    com confidence ≥ 0.95. Retorna '' caso contrário (não é comida, vago,
    ou erro)."""
    text = (text or "").strip()
    if not text or len(text) > 500:
        return ""

    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not api_key:
        return ""

    payload = {
        "model": _GROQ_MODEL,
        "messages": [
            {"role": "system", "content": _DETECTOR_SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
        "max_tokens": 100,
        "temperature": 0.0,
        "response_format": {"type": "json_object"},
    }

    try:
        r = http_requests.post(
            _GROQ_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=15,
        )
        r.raise_for_status()
        raw = r.json()["choices"][0]["message"]["content"]
    except Exception as exc:
        logger.warning("food_image.detect_dish: groq falhou: %s", exc)
        return ""

    try:
        data = json.loads(_strip_json(raw))
    except Exception:
        logger.warning("food_image.detect_dish: JSON inválido: %r", raw[:200])
        return ""

    if not data.get("is_food"):
        return ""
    try:
        conf = float(data.get("confidence", 0))
    except (TypeError, ValueError):
        conf = 0.0
    if conf < _CONFIDENCE_THRESHOLD:
        return ""
    dish = (data.get("dish_name") or "").strip()
    if not dish or len(dish) > 100:
        return ""
    return dish


def generate_dish_image(dish_name: str) -> bytes:
    """Gera uma foto do prato via OpenAI gpt-image-1 e retorna os bytes PNG.
    Retorna b'' em qualquer falha."""
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return b""

    prompt = (
        f"Professional food photography of {dish_name}, "
        "served on a beautiful ceramic plate, restaurant plating, "
        "top-down view, natural soft daylight, shallow depth of field, "
        "appetizing, vibrant colors, no text, no logos, no people."
    )

    try:
        r = http_requests.post(
            _OPENAI_IMAGE_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": _OPENAI_IMAGE_MODEL,
                "prompt": prompt,
                "size": "1024x1024",
                "n": 1,
            },
            timeout=120,
        )
        r.raise_for_status()
        item = r.json()["data"][0]
    except Exception as exc:
        logger.warning("food_image.generate_dish_image: OpenAI falhou: %s", exc)
        return b""

    # gpt-image-1 retorna b64_json; modelos antigos retornavam url.
    if "b64_json" in item and item["b64_json"]:
        try:
            return base64.b64decode(item["b64_json"])
        except Exception as exc:
            logger.warning("food_image.generate_dish_image: b64 decode falhou: %s", exc)
            return b""
    if item.get("url"):
        try:
            ir = http_requests.get(item["url"], timeout=30)
            ir.raise_for_status()
            return ir.content
        except Exception as exc:
            logger.warning("food_image.generate_dish_image: download URL falhou: %s", exc)
            return b""
    return b""


def _has_used_quota_today(user_id: int) -> bool:
    """Já gerou imagem de IA hoje? Cota é 1/dia/usuário."""
    from boards.models import SocialPost
    today = timezone.localdate()
    return (
        SocialPost.objects
        .filter(user_id=user_id, created_at__date=today)
        .exclude(ai_food_dish="")
        .exists()
    )


def _process_post_sync(post_id: int):
    """Pipeline sincrono — chamado dentro do worker thread."""
    from boards.models import SocialPost
    from boards.services.image_compress import compress_image

    try:
        post = SocialPost.objects.select_related("user").get(id=post_id, is_active=True)
    except SocialPost.DoesNotExist:
        return

    # Sanity: só agir em post text-only
    if post.photo or post.video or post.gif_url or post.sticker_url:
        return
    if not post.text or not post.text.strip():
        return
    # Não tocar em markers (__friendship__, __card_like__, __board_invite__)
    if post.text.startswith("__"):
        return
    # Já processado?
    if post.ai_food_dish:
        return

    dish = detect_dish(post.text)
    if not dish:
        return

    # Cota: 1/dia/usuário. Re-checa depois da detecção (a detecção pode
    # rodar pra todo post de texto, mas a geração só acontece se cota livre).
    if _has_used_quota_today(post.user_id):
        logger.info("food_image: cota diária esgotada user_id=%s", post.user_id)
        return

    img_bytes = generate_dish_image(dish)
    if not img_bytes:
        return

    # Compressão pra ficar consistente com upload manual
    upload = SimpleUploadedFile(
        name=f"food_{post.id}.png",
        content=img_bytes,
        content_type="image/png",
    )
    compressed = compress_image(upload) or upload

    post.photo.save(f"food_{post.id}.jpg", compressed, save=False)
    post.ai_food_dish = dish[:120]
    # Texto vira legenda embaixo da imagem — drop do gradient/styled-text
    # pra ficar visualmente consistente com posts comuns de foto+caption.
    post.text_style = None
    post.save(update_fields=["photo", "ai_food_dish", "text_style"])
    logger.info("food_image: gerada user_id=%s post_id=%s dish=%r", post.user_id, post.id, dish)


def schedule_food_image(post_id: int):
    """Agenda o pipeline para rodar em background depois do COMMIT.

    Best-effort: sem retry, sem fila persistente. Em vez de usar
    transaction.on_commit (que exige estar dentro de transação ativa), faz
    fallback pra disparar direto, ambos via thread fire-and-forget."""
    if not _is_enabled():
        return

    def _runner():
        try:
            _process_post_sync(post_id)
        except Exception:
            logger.exception("food_image: erro processando post_id=%s", post_id)

    def _spawn():
        t = threading.Thread(target=_runner, name=f"food-image-{post_id}", daemon=True)
        t.start()

    try:
        transaction.on_commit(_spawn)
    except Exception:
        _spawn()


def _is_enabled() -> bool:
    """Kill switch via env var. AI_FOOD_IMAGES_ENABLED=0 desliga."""
    return os.getenv("AI_FOOD_IMAGES_ENABLED", "1") != "0"
