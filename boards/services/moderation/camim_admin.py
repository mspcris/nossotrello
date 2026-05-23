"""Cliente da API de administração do IDCamim.

Usa o endpoint DELETE /admin/users/:userId (que faz soft delete — active=FALSE).
Requer:
  - settings.CAMIM_ADMIN_API_BASE (ex: https://auth.camim.com.br)
  - settings.CAMIM_ADMIN_API_KEY  (header x-admin-api-key)

O userId é o `sub` que guardamos em UserProfile.camim_sub.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

_TIMEOUT = 10


@dataclass
class CamimAdminResult:
    ok: bool
    status_code: int
    error: str = ""


def _base() -> str:
    return (getattr(settings, "CAMIM_ADMIN_API_BASE", "") or "").rstrip("/")


def _key() -> str:
    return (getattr(settings, "CAMIM_ADMIN_API_KEY", "") or "").strip()


def deactivate_user(camim_sub: str) -> CamimAdminResult:
    """Pede ao IDCamim para desativar a conta. Soft delete (active=FALSE)."""
    if not camim_sub:
        return CamimAdminResult(ok=False, status_code=0, error="camim_sub vazio")
    base = _base()
    key = _key()
    if not base or not key:
        return CamimAdminResult(
            ok=False, status_code=0,
            error="CAMIM_ADMIN_API_BASE/CAMIM_ADMIN_API_KEY não configurados",
        )
    url = f"{base}/admin/users/{camim_sub}"
    try:
        resp = requests.delete(
            url,
            headers={"x-admin-api-key": key, "Accept": "application/json"},
            timeout=_TIMEOUT,
        )
    except requests.RequestException as e:
        logger.exception("camim_admin.deactivate_user: requisição falhou")
        return CamimAdminResult(ok=False, status_code=0, error=str(e))

    if 200 <= resp.status_code < 300:
        return CamimAdminResult(ok=True, status_code=resp.status_code)
    return CamimAdminResult(
        ok=False, status_code=resp.status_code, error=resp.text[:500],
    )
