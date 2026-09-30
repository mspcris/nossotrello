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


def update_user_phone(camim_sub: str, phone_number: str) -> CamimAdminResult:
    """Grava o telefone do usuário no IDCamim (PATCH /admin/users/:sub).

    Usado quando o usuário tem telefone salvo aqui mas não no IDCamim, para
    manter o IDCamim como fonte da verdade daqui pra frente.
    """
    if not camim_sub:
        return CamimAdminResult(ok=False, status_code=0, error="camim_sub vazio")
    phone_number = (phone_number or "").strip()
    if not phone_number:
        return CamimAdminResult(ok=False, status_code=0, error="phone vazio")
    base = _base()
    key = _key()
    if not base or not key:
        return CamimAdminResult(
            ok=False, status_code=0,
            error="CAMIM_ADMIN_API_BASE/CAMIM_ADMIN_API_KEY não configurados",
        )
    url = f"{base}/admin/users/{camim_sub}"
    try:
        resp = requests.patch(
            url,
            json={"phone_number": phone_number},
            headers={
                "x-admin-api-key": key,
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            timeout=_TIMEOUT,
        )
    except requests.RequestException as e:
        logger.exception("camim_admin.update_user_phone: requisição falhou")
        return CamimAdminResult(ok=False, status_code=0, error=str(e))

    if 200 <= resp.status_code < 300:
        return CamimAdminResult(ok=True, status_code=resp.status_code)
    return CamimAdminResult(
        ok=False, status_code=resp.status_code, error=resp.text[:500],
    )


def fetch_inactive_users() -> tuple[list[dict] | None, str]:
    """Lista as contas desativadas no IDCamim (GET /api/clientes/usuarios-inativos).

    Autentica com as credenciais OAuth do Tarefas (Basic CAMIM_CLIENT_ID:
    CAMIM_CLIENT_SECRET). Retorna (usuarios, "") ou (None, erro) — None
    significa "não sei", e quem chama NÃO deve reativar ninguém nesse caso.
    Cada item: {"sub", "email", "desativado_em", "motivo"}.
    """
    base = _base()
    client_id = (getattr(settings, "CAMIM_CLIENT_ID", "") or "").strip()
    client_secret = (getattr(settings, "CAMIM_CLIENT_SECRET", "") or "").strip()
    if not base or not client_id or not client_secret:
        return None, "CAMIM_ADMIN_API_BASE/CAMIM_CLIENT_ID/CAMIM_CLIENT_SECRET não configurados"
    try:
        resp = requests.get(
            f"{base}/api/clientes/usuarios-inativos",
            auth=(client_id, client_secret),
            headers={"Accept": "application/json"},
            timeout=30,
        )
    except requests.RequestException as e:
        logger.exception("camim_admin.fetch_inactive_users: requisição falhou")
        return None, str(e)
    if resp.status_code != 200:
        return None, f"HTTP {resp.status_code}: {resp.text[:300]}"
    try:
        usuarios = resp.json().get("usuarios")
    except ValueError:
        return None, "resposta não é JSON"
    if not isinstance(usuarios, list):
        return None, "resposta sem a lista 'usuarios'"
    return usuarios, ""
