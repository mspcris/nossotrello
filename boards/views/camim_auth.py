# boards/views/camim_auth.py
"""
Login com IDCamim — OAuth2/OIDC
Qualquer usuário autenticado pelo IDCamim pode logar.
Se não existir conta local, cria automaticamente na primeira vez.
"""
import logging
import secrets
import urllib.parse

import requests
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.shortcuts import redirect
from django.views.decorators.http import require_GET

from boards.services.camim_identity import resolve_or_create_camim_user

logger = logging.getLogger(__name__)

CAMIM_BASE     = "https://auth.camim.com.br"
AUTHORIZE_URL  = f"{CAMIM_BASE}/auth"
TOKEN_URL      = f"{CAMIM_BASE}/token"
USERINFO_URL   = f"{CAMIM_BASE}/me"

User = get_user_model()


def _sync_camim_phone(user, *, sub: str, idcamim_phone: str) -> None:
    """Sincroniza telefone entre IDCamim e o perfil local (best-effort).

    - IDCamim tem telefone e local está vazio  → salva no perfil local.
    - Local tem telefone e IDCamim está vazio   → empurra pro IDCamim (PATCH admin).
    - Ambos preenchidos                          → IDCamim manda; atualiza local se diferiu.
    Nunca quebra o login: qualquer erro é engolido com log.
    """
    try:
        from boards.models import UserProfile
        prof, _ = UserProfile.objects.get_or_create(user=user)
        local_phone = (getattr(prof, "telefone", "") or "").strip()
        idcamim_phone = (idcamim_phone or "").strip()

        if idcamim_phone:
            if local_phone != idcamim_phone:
                prof.telefone = idcamim_phone[:30]
                prof.save(update_fields=["telefone"])
        elif local_phone and sub:
            # IDCamim não tem; manda o daqui pra lá.
            from boards.services.moderation.camim_admin import update_user_phone
            res = update_user_phone(sub, local_phone)
            if not res.ok:
                logger.warning("push telefone->IDCamim falhou: %s", res.error)
    except Exception:
        logger.exception("sync de telefone IDCamim falhou (ignorado)")


def _client_id():
    return (getattr(settings, "CAMIM_CLIENT_ID", "") or "").strip()


def _client_secret():
    return (getattr(settings, "CAMIM_CLIENT_SECRET", "") or "").strip()


def _redirect_uri():
    base = (getattr(settings, "SITE_URL", "") or "").rstrip("/")
    return f"{base}/auth/camim/callback/"


# ──────────────────────────────────────────────────────────────────
# Passo 1: redireciona o usuário para auth.camim.com.br/authorize
# ──────────────────────────────────────────────────────────────────
@require_GET
def camim_login(request):
    client_id = _client_id()
    if not client_id:
        messages.error(request, "Login com Camim não está configurado.")
        return redirect("boards:login")

    state = secrets.token_urlsafe(24)
    request.session["camim_oauth_state"] = state

    # Guarda o "next" para redirecionar após login
    next_url = request.GET.get("next", "/")
    request.session["camim_next"] = next_url

    params = urllib.parse.urlencode({
        "client_id":     client_id,
        "redirect_uri":  _redirect_uri(),
        "response_type": "code",
        "scope":         "openid profile email phone",
        "state":         state,
    })
    return redirect(f"{AUTHORIZE_URL}?{params}")


# ──────────────────────────────────────────────────────────────────
# Passo 2: recebe o código, troca por token, valida usuário
# ──────────────────────────────────────────────────────────────────
@require_GET
def camim_callback(request):
    # Verifica erro vindo do Camim
    error = request.GET.get("error")
    if error:
        messages.error(request, f"Erro ao autenticar com Camim: {error}")
        return redirect("boards:login")

    # Verifica state (anti-CSRF)
    state         = request.GET.get("state", "")
    expected_state = request.session.pop("camim_oauth_state", None)
    if not expected_state or state != expected_state:
        messages.error(request, "Sessão inválida. Tente novamente.")
        return redirect("boards:login")

    code = request.GET.get("code", "")
    if not code:
        messages.error(request, "Código de autorização não recebido.")
        return redirect("boards:login")

    client_id     = _client_id()
    client_secret = _client_secret()

    # ── Troca código por access_token ────────────────────────────
    try:
        token_resp = requests.post(
            TOKEN_URL,
            auth=(client_id, client_secret),
            data={
                "grant_type":   "authorization_code",
                "code":         code,
                "redirect_uri": _redirect_uri(),
            },
            timeout=10,
        )
        token_resp.raise_for_status()
        tokens = token_resp.json()
    except Exception as exc:
        messages.error(request, "Falha ao obter token do Camim. Tente novamente.")
        return redirect("boards:login")

    access_token = tokens.get("access_token", "")
    if not access_token:
        messages.error(request, "Token inválido retornado pelo Camim.")
        return redirect("boards:login")

    # ── Busca dados do usuário ────────────────────────────────────
    try:
        user_resp = requests.get(
            USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10,
        )
        user_resp.raise_for_status()
        userinfo = user_resp.json()
    except Exception as exc:
        logger.exception("CAMIM /me falhou: %s", exc)
        messages.error(request, "Falha ao buscar dados do usuário no Camim.")
        return redirect("boards:login")

    email = (userinfo.get("email") or "").strip().lower()
    if not email:
        messages.error(request, "E-mail não retornado pelo Camim.")
        return redirect("boards:login")

    sub = (userinfo.get("sub") or "").strip()

    # ── Busca ou cria o usuário (preferindo sub) ─────────────────
    name       = (userinfo.get("name") or "").strip()
    first_name = (userinfo.get("given_name") or name.split()[0] if name else "").strip()
    last_name  = (userinfo.get("family_name") or " ".join(name.split()[1:]) if name else "").strip()

    user = resolve_or_create_camim_user(
        sub=sub, email=email, first_name=first_name, last_name=last_name,
    )

    # Telefone: IDCamim é a fonte da verdade. Se ele mandou telefone, salva aqui
    # (quando local está vazio). Se local tem e o IDCamim não, empurra pro IDCamim.
    _sync_camim_phone(user, sub=sub, idcamim_phone=(userinfo.get("phone_number") or "").strip())

    if not user.is_active:
        messages.error(request, "Sua conta está inativa. Fale com o administrador.")
        return redirect("boards:login")

    # ── Loga o usuário ────────────────────────────────────────────
    login(request, user, backend="boards.auth_backends.UsernameOrEmailBackend")

    next_url = request.session.pop("camim_next", "/")
    # Garante que o next é seguro (mesma origem). Bloqueia '//host' (open redirect).
    if (not next_url
            or not next_url.startswith("/")
            or next_url.startswith("//")
            or next_url.startswith("/\\")):
        next_url = "/"

    return redirect(next_url)
