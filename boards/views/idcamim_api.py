# boards/views/idcamim_api.py
"""
API server-to-server consumida pelo idCamim.

POST /api/idcamim/whatsapp/ — envia uma mensagem de WhatsApp pelo Evolution
usando a instância DO CHAMADOR (o idCamim tem a dele, ex.: "CRM"), não a do
Tarefas. O Tarefas entra só com o que o idCamim não tem: o telefone do perfil
daqui quando o idCamim não tem telefone cadastrado, e o cliente Evolution.

Autenticação: header `X-Evolution-Token` com o token da instância no Evolution.
O token é conferido NO PRÓPRIO EVOLUTION (`GET /instance/fetchInstances`): se
ele aceitar e devolver exatamente uma instância, o chamador é legítimo e é por
essa instância que a mensagem sai. Token inválido → 401. Nada de segredo
compartilhado para manter em dois lugares.

Body JSON:
    {"email": "fulano@camim.com.br", "phone": "(21) 9...", "text": "..."}

Respostas:
    200 {"ok": true,  "instance": "CRM", "source": "idcamim"|"tarefas", "number_masked": "5521*****2098"}
    401 {"ok": false, "error": "unauthorized"}              — Evolution recusou o token
    404 {"ok": false, "error": "sem_telefone"}              — nem idCamim nem Tarefas têm número
    409 {"ok": false, "error": "instancia_desconectada"}    — instância existe mas está sem WhatsApp
    502 {"ok": false, "error": "evolution", ...}            — Evolution caiu/recusou o envio
"""
from __future__ import annotations

import json
import logging
import re
from urllib import error, request

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from tracktime.services.evolution import EvolutionError, send_text_message

logger = logging.getLogger(__name__)

TOKEN_HEADER = "HTTP_X_EVOLUTION_TOKEN"


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


def resolve_instance(base_url: str, token: str) -> tuple[dict | None, str]:
    """
    Pergunta ao Evolution de quem é este token.

    Retorna (instancia, "") ou (None, motivo). `instancia` = {"name", "state"}.
    Um token de instância só enxerga a própria instância; a chave global
    enxerga todas — e aí não dá para saber por qual enviar (token_ambiguo).
    """
    if not token:
        return None, "unauthorized"
    req = request.Request(
        url=f"{base_url.rstrip('/')}/instance/fetchInstances",
        method="GET",
        headers={"apikey": token},
    )
    try:
        with request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace") or "[]")
    except error.HTTPError as e:
        if e.code in (401, 403):
            return None, "unauthorized"
        return None, f"evolution_http_{e.code}"
    except Exception as e:  # rede, timeout, JSON
        logger.warning("idcamim_api: fetchInstances falhou: %s", e)
        return None, "evolution_indisponivel"

    if isinstance(data, dict):
        data = [data]
    items = []
    for i in data if isinstance(data, list) else []:
        if not isinstance(i, dict):
            continue
        inner = i.get("instance") if isinstance(i.get("instance"), dict) else {}
        name = i.get("name") or inner.get("instanceName")
        state = i.get("connectionStatus") or inner.get("status") or inner.get("state")
        if name:
            items.append({"name": str(name), "state": str(state or "")})

    if len(items) != 1:
        return None, "token_ambiguo" if items else "unauthorized"
    return items[0], ""


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
    base_url = (getattr(settings, "EVOLUTION_BASE_URL", "") or "").strip()
    if not base_url:
        return JsonResponse(
            {"ok": False, "error": "evolution_nao_configurado", "message": "EVOLUTION_BASE_URL não configurada no Tarefas."},
            status=503,
        )

    token = (request.META.get(TOKEN_HEADER) or "").strip()
    instance, why = resolve_instance(base_url, token)
    if not instance:
        status = 401 if why in ("unauthorized", "token_ambiguo") else 502
        msg = {
            "unauthorized": "O Evolution não reconheceu este token de instância.",
            "token_ambiguo": "Este token enxerga várias instâncias (chave global?). Use o token de UMA instância.",
        }.get(why, "Evolution indisponível para validar o token.")
        logger.info("idcamim_api: token recusado (%s)", why)
        return JsonResponse({"ok": False, "error": why, "message": msg}, status=status)

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

    if instance["state"] and instance["state"] != "open":
        return JsonResponse(
            {
                "ok": False,
                "error": "instancia_desconectada",
                "instance": instance["name"],
                "message": f"A instância {instance['name']} está '{instance['state']}' no Evolution — reconecte o WhatsApp dela.",
            },
            status=409,
        )

    try:
        send_text_message(
            base_url=base_url,
            api_key=token,
            instance=instance["name"],
            number=number,
            body=text,
        )
    except EvolutionError as exc:
        logger.warning("idcamim_api: evolution falhou instance=%s email=%s number=%s: %s", instance["name"], email, _mask(number), exc)
        return JsonResponse({"ok": False, "error": "evolution", "instance": instance["name"], "message": str(exc)}, status=502)

    logger.info("idcamim_api: whatsapp enviado instance=%s email=%s source=%s number=%s", instance["name"], email, source, _mask(number))
    return JsonResponse({"ok": True, "instance": instance["name"], "source": source, "number_masked": _mask(number)})
