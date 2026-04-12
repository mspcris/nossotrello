"""
Soft locks para edição colaborativa de campos de card.

Um usuário A clica num campo (title/description) de um card — o client pede
um lock via `acquire()`. O lock fica no Redis com TTL de 15s. Enquanto A
digita, cada evento de `typing` renova o TTL via `refresh()`. Outros usuários
do mesmo board veem o campo como read-only com overlay "✏️ A editando…" e
recebem o texto via WS (ver `card_edit_collab.py`).

No blur, o client chama `release()`, que apaga o lock. O valor final é
persistido no banco pelo próprio endpoint de release, antes da publicação
do evento WS.

Se A fechar a aba sem blur (browser crash, ALT-F4, network drop), o TTL
expira sozinho em até 15 segundos — ninguém fica preso.

As operações são *best-effort*: se o Redis cair, `acquire()` retorna
`(True, None)` (fallback permissivo) pra não travar a UI. O risco é write
conflict, mas é o mesmo do mundo sem lock que existia até ontem.
"""

from __future__ import annotations

import logging
from typing import Optional

from django_redis import get_redis_connection

logger = logging.getLogger(__name__)

LOCK_TTL_SECONDS = 15
LOCK_KEY_FMT = "card_edit_lock:{card_id}:{field}"


def _conn():
    try:
        return get_redis_connection("default")
    except Exception:  # noqa: BLE001
        logger.warning("edit_locks: redis indisponível", exc_info=True)
        return None


def _key(card_id: int, field: str) -> str:
    return LOCK_KEY_FMT.format(card_id=card_id, field=field)


def _parse_holder(value) -> Optional[dict]:
    if value is None:
        return None
    text = value.decode("utf-8") if isinstance(value, (bytes, bytearray)) else str(value)
    try:
        holder_id_s, holder_name = text.split(":", 1)
        return {"user_id": int(holder_id_s), "username": holder_name}
    except Exception:  # noqa: BLE001
        return None


def acquire(
    card_id: int, field: str, user_id: int, username: str
) -> tuple[bool, Optional[dict]]:
    """
    Tenta adquirir o lock (SETNX + TTL). Retorna (acquired, holder).

    - acquired=True, holder={user_id, username}  -> lock é seu (ou você renovou o seu)
    - acquired=False, holder={...}               -> outro usuário segura o lock
    - acquired=True, holder=None                 -> fallback (redis down)
    """
    r = _conn()
    if r is None:
        return True, None

    key = _key(card_id, field)
    value = f"{user_id}:{username}"

    try:
        ok = r.set(key, value, nx=True, ex=LOCK_TTL_SECONDS)
    except Exception:  # noqa: BLE001
        logger.warning("edit_locks: SETNX falhou, fallback permissivo", exc_info=True)
        return True, None

    if ok:
        return True, {"user_id": user_id, "username": username}

    # Já existe lock; verifica se é o próprio caller
    try:
        current = r.get(key)
    except Exception:  # noqa: BLE001
        return True, None

    holder = _parse_holder(current)
    if holder is None:
        # entre SETNX e GET, o lock expirou; tenta de novo uma vez
        try:
            ok = r.set(key, value, nx=True, ex=LOCK_TTL_SECONDS)
        except Exception:  # noqa: BLE001
            return True, None
        if ok:
            return True, {"user_id": user_id, "username": username}
        return False, None

    if holder["user_id"] == user_id:
        try:
            r.expire(key, LOCK_TTL_SECONDS)
        except Exception:  # noqa: BLE001
            pass
        return True, holder

    return False, holder


def refresh(card_id: int, field: str, user_id: int) -> bool:
    """
    Renova o TTL se o lock ainda pertence a `user_id`. True se renovou.
    """
    r = _conn()
    if r is None:
        return True

    key = _key(card_id, field)
    try:
        current = r.get(key)
    except Exception:  # noqa: BLE001
        return False

    holder = _parse_holder(current)
    if holder is None or holder["user_id"] != user_id:
        return False

    try:
        r.expire(key, LOCK_TTL_SECONDS)
    except Exception:  # noqa: BLE001
        return False
    return True


def release(card_id: int, field: str, user_id: int) -> bool:
    """
    Libera o lock se pertencer a `user_id`. True se liberado (ou já estava).
    """
    r = _conn()
    if r is None:
        return True

    key = _key(card_id, field)
    try:
        current = r.get(key)
    except Exception:  # noqa: BLE001
        return False

    if current is None:
        return True

    holder = _parse_holder(current)
    if holder is None:
        # lixo — apaga
        try:
            r.delete(key)
        except Exception:  # noqa: BLE001
            pass
        return True

    if holder["user_id"] != user_id:
        return False

    try:
        r.delete(key)
    except Exception:  # noqa: BLE001
        return False
    return True


def get_holder(card_id: int, field: str) -> Optional[dict]:
    r = _conn()
    if r is None:
        return None

    key = _key(card_id, field)
    try:
        current = r.get(key)
    except Exception:  # noqa: BLE001
        return None

    return _parse_holder(current)
