"""Porta de entrada da fila de tarefas.

`enqueue()` tenta pôr o trabalho na fila; se a fila está desligada (dev) ou o
broker não responde, executa pelo caminho ANTIGO — thread daemon ou chamada
direta — para nada deixar de acontecer por causa da fila.
"""
from __future__ import annotations

import logging
import threading
import time

from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

# O worker-ordered renova esta chave a cada 10 s (tarefa do beat roteada para a
# própria fila board_ops). Ela prova a cadeia inteira: beat -> broker -> worker.
BOARD_OPS_ALIVE_KEY = "nt:jobs:board_ops:alive"
BOARD_OPS_ALIVE_TTL = 45


def queue_enabled() -> bool:
    return bool(getattr(settings, "TASK_QUEUE_ENABLED", False))


def _run_fallback(fallback, mode: str, name: str) -> None:
    if fallback is None or mode == "none":
        return

    def _safe():
        try:
            fallback()
        except Exception:
            logger.exception("jobs: fallback de %s falhou", name)

    if mode == "thread":
        threading.Thread(target=_safe, name=f"job-fallback-{name}", daemon=True).start()
    else:
        _safe()


def enqueue(task, *args, fallback=None, mode: str = "thread", countdown=None, **kwargs) -> bool:
    """Enfileira `task(*args, **kwargs)`. Devolve True se foi para a fila.

    fallback: callable sem argumentos com o caminho antigo.
    mode: "thread" (daemon, como era antes), "sync" (na hora) ou "none".
    """
    name = getattr(task, "name", str(task))
    if queue_enabled():
        try:
            # retry=False: broker fora do ar tem que falhar JÁ, não segurar a requisição
            task.apply_async(args=args, kwargs=kwargs, countdown=countdown, retry=False)
            return True
        except Exception:
            logger.warning("jobs: broker indisponível; %s segue pelo caminho antigo (%s)", name, mode, exc_info=True)
    _run_fallback(fallback, mode, name)
    return False


def mark_board_ops_alive() -> None:
    try:
        cache.set(BOARD_OPS_ALIVE_KEY, time.time(), BOARD_OPS_ALIVE_TTL)
    except Exception:
        pass


def board_ops_alive() -> bool:
    """Há um consumidor vivo na fila ordenada? Sem ele, mover card volta a ser síncrono."""
    if not queue_enabled():
        return False
    try:
        return cache.get(BOARD_OPS_ALIVE_KEY) is not None
    except Exception:
        return False
