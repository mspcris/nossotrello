# tracktime/services/pressticket.py
from __future__ import annotations

import json
import logging
from urllib import request, error

logger = logging.getLogger(__name__)


class PressTicketError(RuntimeError):
    pass


def send_text_message(
    *,
    base_url: str,
    token: str,
    number: str,
    body: str,
    user_id: int,
    queue_id: int,
    whatsapp_id: int,
    timeout_seconds: int = 12,
) -> dict:
    """
    Envia mensagem de texto pelo PressTicket.
    number deve estar no formato: 55 + DDD + número (apenas dígitos).
    """
    if not token:
        raise PressTicketError("PRESSTICKET_TOKEN vazio")
    if not base_url:
        raise PressTicketError("PRESSTICKET_BASE_URL vazio")
    if not number or not number.isdigit():
        raise PressTicketError("Número inválido (esperado somente dígitos, ex: 5521999999999)")
    if not user_id or not queue_id or not whatsapp_id:
        raise PressTicketError("IDs do PressTicket não configurados (user/queue/whatsapp)")

    url = base_url.rstrip("/")

    payload = {
        "number": number,
        "body": body,
        "userId": int(user_id),
        "queueId": int(queue_id),
        "whatsappId": int(whatsapp_id),
    }

    data = json.dumps(payload).encode("utf-8")

    req = request.Request(
        url=url,
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },

    )

    try:
        with request.urlopen(req, timeout=timeout_seconds) as resp:
            raw = resp.read().decode("utf-8", errors="replace").strip()
            if not raw:
                return {}
            try:
                return json.loads(raw)
            except Exception:
                return {"raw": raw}
    except error.HTTPError as e:
        raw = ""
        try:
            raw = e.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        raise PressTicketError(f"HTTP {e.code} ao enviar WhatsApp: {raw or e.reason}") from e
    except Exception as e:
        raise PressTicketError(f"Falha ao enviar WhatsApp: {e}") from e
