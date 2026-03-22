# tracktime/services/evolution.py
from __future__ import annotations

import json
import logging
from urllib import request, error

logger = logging.getLogger(__name__)


class EvolutionError(RuntimeError):
    pass


def send_text_message(
    *,
    base_url: str,
    api_key: str,
    instance: str,
    number: str,
    body: str,
    timeout_seconds: int = 12,
) -> dict:
    """
    Envia mensagem de texto pelo Evolution API.
    number deve estar no formato: 55 + DDD + número (apenas dígitos).
    """
    if not api_key:
        raise EvolutionError("EVOLUTION_API_KEY vazio")
    if not base_url:
        raise EvolutionError("EVOLUTION_BASE_URL vazio")
    if not instance:
        raise EvolutionError("EVOLUTION_INSTANCE vazio")
    if not number or not number.isdigit():
        raise EvolutionError("Número inválido (esperado somente dígitos, ex: 5521999999999)")

    base = (base_url or "").rstrip("/")
    url = f"{base}/message/sendText/{instance}"

    payload = {
        "number": number,
        "text": body,
    }

    data = json.dumps(payload).encode("utf-8")

    req = request.Request(
        url=url,
        data=data,
        method="POST",
        headers={
            "apikey": api_key,
            "Content-Type": "application/json",
        },
    )

    try:
        with request.urlopen(req, timeout=timeout_seconds) as resp:
            raw = resp.read().decode("utf-8", errors="replace").strip()
            if not raw:
                return {}
            try:
                obj = json.loads(raw)
                msg_id = None
                if isinstance(obj, dict):
                    msg_id = obj.get("key", {}).get("id") if isinstance(obj.get("key"), dict) else None
                logger.info("evolution: api ok msg_id=%r", msg_id)
                return obj
            except Exception:
                return {"raw": raw}
    except error.HTTPError as e:
        raw = ""
        try:
            raw = e.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        raise EvolutionError(f"HTTP {e.code} ao enviar WhatsApp: {raw or e.reason}") from e
    except Exception as e:
        raise EvolutionError(f"Falha ao enviar WhatsApp: {e}") from e
