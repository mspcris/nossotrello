"""Domínios de e-mail permitidos a criar login / receber convite automático.

Fonte = UNION de duas origens:
  1. `settings.INSTITUTIONAL_EMAIL_DOMAINS` (lista fixa, base do projeto)
  2. tabela `AllowedEmailDomain` ativa (editável pela Direção no /admin)

Cacheado por _CACHE_TTL pra não bater no banco em todo login/convite. O admin
invalida o cache em save/delete (ver boards/admin.py).
"""
from __future__ import annotations

from django.conf import settings
from django.core.cache import cache

_CACHE_KEY = "auth:allowed_email_domains:v1"
_CACHE_TTL = 60  # 1 min — suficiente pro admin ver a mudança logo


def _settings_domains() -> set[str]:
    raw = getattr(settings, "INSTITUTIONAL_EMAIL_DOMAINS", []) or []
    return {d.strip().lower() for d in raw if d and d.strip()}


def allowed_email_domains() -> set[str]:
    """Conjunto normalizado (minúsculas) de domínios permitidos. Cacheado."""
    cached = cache.get(_CACHE_KEY)
    if cached is not None:
        return cached

    domains = _settings_domains()

    from boards.models import AllowedEmailDomain
    db_domains = (
        AllowedEmailDomain.objects
        .filter(active=True)
        .values_list("domain", flat=True)
    )
    domains.update(d.strip().lower() for d in db_domains if d and d.strip())

    cache.set(_CACHE_KEY, domains, _CACHE_TTL)
    return domains


def is_allowed_email(email: str) -> bool:
    email = (email or "").strip().lower()
    if "@" not in email:
        return False
    domain = email.rsplit("@", 1)[-1]
    allowed = allowed_email_domains()
    return (not allowed) or (domain in allowed)


def invalidate_cache() -> None:
    cache.delete(_CACHE_KEY)
