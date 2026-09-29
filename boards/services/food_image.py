"""Detecção de comida em posts de texto + geração de foto do prato.

Tudo pela OpenRouter (boards/services/openrouter.py).

Fluxo (chamado em background por process_food_post):
    1. detect_dish(text) usa um LLM pra decidir se o texto é uma menção a uma
       comida CONHECIDA com confiança ≥ 0.95, e retornar o nome canônico
       do prato (ex: "Strogonoff de carne"). Sem foto → None.
    2. Checa cota (1/dia/usuário). Já bateu → desiste.
    3. generate_dish_image(dish_name) gera a foto do prato (Gemini 2.5 Flash Image,
       via chat com modalities=[image, text]).
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

_CONFIDENCE_THRESHOLD = 0.85

_DETECTOR_SYSTEM_PROMPT = (
    "Você é um detector de pratos de comida em posts curtos de rede social. "
    "Receba o texto e responda APENAS um JSON com este formato exato:\n"
    '{"is_food": true|false, "confidence": 0.0-1.0, "dish_name": "Nome canônico do prato em português"}\n'
    "Regras:\n"
    "- is_food=true SÓ se o texto menciona claramente um prato de comida REAL e CONHECIDO "
    "(ex: Strogonoff, Feijoada, Lasanha, Pizza Margherita, Tapioca, Bobó de camarão, Sushi, "
    "Hambúrguer, Macarrão à bolonhesa).\n"
    "- confidence ≥ 0.85 quando o texto descreve uma refeição reconhecível "
    "(ex: 'Frango com batata', 'Arroz feijão e bife', 'Macarrão com molho de tomate' contam). "
    "Frases vagas como 'comi um lanche', 'almoço gostoso', 'um docinho' devem ter confidence baixa.\n"
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

    from boards.services import openrouter

    if not openrouter.is_configured():
        return ""

    try:
        raw = openrouter.chat(
            [
                {"role": "system", "content": _DETECTOR_SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            model=openrouter.MODEL_FOOD_DETECT,
            max_tokens=100,
            temperature=0.0,
            response_format={"type": "json_object"},
            timeout=15,
        )
    except Exception as exc:
        logger.warning("food_image.detect_dish: IA falhou: %s", exc)
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
    """Gera uma foto do prato pela OpenRouter e retorna os bytes da imagem (PNG).
    Retorna b'' em qualquer falha.

    A OpenRouter não tem /images/generations: imagem sai do chat com
    modalities=["image", "text"] e volta em message.images[].image_url.url
    como data URL base64."""
    from boards.services import openrouter

    client = openrouter.get_client()
    if client is None:
        return b""

    prompt = (
        f"Professional food photography of {dish_name}, "
        "served on a beautiful ceramic plate, restaurant plating, "
        "top-down view, natural soft daylight, shallow depth of field, "
        "appetizing, vibrant colors, no text, no logos, no people."
    )

    try:
        resp = client.with_options(timeout=120).chat.completions.create(
            model=openrouter.MODEL_IMAGE,
            messages=[{"role": "user", "content": prompt}],
            extra_body={
                **openrouter.PROVIDER_CHEAPEST,
                "modalities": ["image", "text"],
                "image_config": {"aspect_ratio": "1:1"},
            },
        )
        msg = resp.choices[0].message.model_dump()
        images = msg.get("images") or []
        url = ((images[0] or {}).get("image_url") or {}).get("url", "") if images else ""
    except Exception as exc:
        logger.warning("food_image.generate_dish_image: OpenRouter falhou: %s", exc)
        return b""

    if not url:
        logger.warning("food_image.generate_dish_image: resposta sem imagem")
        return b""
    if url.startswith("data:"):
        try:
            return base64.b64decode(url.split(",", 1)[1])
        except Exception as exc:
            logger.warning("food_image.generate_dish_image: b64 decode falhou: %s", exc)
            return b""
    try:
        ir = http_requests.get(url, timeout=30)
        ir.raise_for_status()
        return ir.content
    except Exception as exc:
        logger.warning("food_image.generate_dish_image: download URL falhou: %s", exc)
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

    def _spawn():
        from boards.services.jobs import enqueue
        from boards.tasks import food_image_post

        enqueue(food_image_post, post_id, fallback=lambda: run_food_image_job(post_id), mode="thread")

    try:
        transaction.on_commit(_spawn)
    except Exception:
        _spawn()


def run_food_image_job(post_id: int) -> None:
    """Roda no worker da fila "media" (ou na thread de reserva)."""
    try:
        _process_post_sync(post_id)
    except Exception:
        logger.exception("food_image: erro processando post_id=%s", post_id)


def _is_enabled() -> bool:
    """Kill switch via env var. AI_FOOD_IMAGES_ENABLED=0 desliga."""
    return os.getenv("AI_FOOD_IMAGES_ENABLED", "1") != "0"
