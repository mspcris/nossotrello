# boards/views/idcamim_api.py
"""
API server-to-server consumida pelo idCamim.

POST /api/idcamim/whatsapp/ — envia uma mensagem de WhatsApp pelo Evolution
(mesma instância "Tarefas" usada nas notificações de card).

Uso hoje: link de redefinição de senha do idCamim. O idCamim manda o telefone
cadastrado lá; se vier vazio, usamos o telefone do perfil do usuário DAQUI
com o mesmo e-mail (fallback "usa o do tarefas").

Autenticação: header `X-IdCamim-Token` igual a `IDCAMIM_ZAP_TOKEN` (.env).
Sem token configurado o endpoint fica desligado (503) — nunca aberto.

Body JSON:
    {"email": "fulano@camim.com.br", "phone": "(21) 9...", "text": "..."}

Respostas:
    200 {"ok": true,  "source": "idcamim"|"tarefas", "number_masked": "5521*****2098"}
    404 {"ok": false, "error": "sem_telefone"}      — nem idCamim nem Tarefas têm número
    502 {"ok": false, "error": "evolution", ...}     — Evolution recusou/caiu
"""
from __future__ import annotations

import hmac
import json
import logging
import re

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from tracktime.services.evolution import EvolutionError, send_text_message

logger = logging.getLogger(__name__)

TOKEN_HEADER = "HTTP_X_IDCAMIM_TOKEN"


def normalize_phone(raw) -> str:
    """
    Converte o que o usuário digitou em número Evolution: 55 + DDD + número.

    Aceita "(021) 990772098", "21 96486-7974", "+55 (21) 970-066-540"...
    Devolve "" quando não dá para montar um número válido.
    """
    digits = re.sub(r"\D+", "", str(raw or ""))
    if not digits:
        return ""

    # DDD escrito com zero na frente ("021") — muito comum no cadastro do idCamim.
    if len(digits) in (11, 12) and digits.startswith("0"):
        digits = digits.lstrip("0")

    if len(digits) in (10, 11):
        digits = "55" + digits

    if len(digits) in (12, 13) and digits.startswith("55"):
        return digits
    return ""


def _mask(number: str) -> str:
    if len(number) <= 8:
        return "*" * len(number)
    return number[:4] + "*" * (len(number) - 8) + number[-4:]


def _authorized(request) -> bool | None:
    """True/False = token conferido; None = endpoint sem token configurado."""
    expected = (getattr(settings, "IDCAMIM_ZAP_TOKEN", "") or "").strip()
    if not expected:
        return None
    given = (request.META.get(TOKEN_HEADER) or "").strip()
    return bool(given) and hmac.compare_digest(given, expected)


def _phone_from_tarefas(email: str) -> str:
    User = get_user_model()
    user = (
        User.objects.filter(Q(email__iexact=email) | Q(username__iexact=email))
        .select_related("profile")
        .order_by("id")
        .first()
    )
    if not user:
        return ""
    prof = getattr(user, "profile", None)
    return (getattr(prof, "telefone", "") or "").strip() if prof else ""


@csrf_exempt
@require_POST
def whatsapp(request):
    auth = _authorized(request)
    if auth is None:
        return JsonResponse(
            {"ok": False, "error": "nao_configurado", "message": "IDCAMIM_ZAP_TOKEN não configurado no Tarefas."},
            status=503,
        )
    if not auth:
        return JsonResponse({"ok": False, "error": "unauthorized"}, status=401)

    try:
        body = json.loads(request.body or b"{}")
        if not isinstance(body, dict):
            raise ValueError("body não é objeto")
    except Exception:
        return JsonResponse({"ok": False, "error": "json_invalido"}, status=400)

    email = (body.get("email") or "").strip().lower()
    text = (body.get("text") or "").strip()
    if not email or not text:
        return JsonResponse({"ok": False, "error": "campos_obrigatorios", "message": "email e text são obrigatórios."}, status=400)

    number = normalize_phone(body.get("phone"))
    source = "idcamim"
    if not number:
        number = normalize_phone(_phone_from_tarefas(email))
        source = "tarefas"

    if not number:
        logger.info("idcamim_api: whatsapp sem telefone email=%s", email)
        return JsonResponse(
            {"ok": False, "error": "sem_telefone", "message": "Nenhum telefone válido no idCamim nem no Tarefas."},
            status=404,
        )

    base_url = (getattr(settings, "EVOLUTION_BASE_URL", "") or "").strip()
    api_key = (getattr(settings, "EVOLUTION_API_KEY", "") or "").strip()
    instance = (getattr(settings, "EVOLUTION_INSTANCE", "") or "").strip()
    if not (base_url and api_key and instance):
        return JsonResponse(
            {"ok": False, "error": "evolution_nao_configurado", "message": "Evolution API não configurada no Tarefas."},
            status=503,
        )

    try:
        send_text_message(
            base_url=base_url,
            api_key=api_key,
            instance=instance,
            number=number,
            body=text,
        )
    except EvolutionError as exc:
        logger.warning("idcamim_api: evolution falhou email=%s number=%s: %s", email, _mask(number), exc)
        return JsonResponse({"ok": False, "error": "evolution", "message": str(exc)}, status=502)

    logger.info("idcamim_api: whatsapp enviado email=%s source=%s number=%s", email, source, _mask(number))
    return JsonResponse({"ok": True, "source": source, "number_masked": _mask(number)})
