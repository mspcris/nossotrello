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

logger = logging.getLogger(__name__)

CAMIM_BASE     = "https://auth.camim.com.br"
AUTHORIZE_URL  = f"{CAMIM_BASE}/auth"
TOKEN_URL      = f"{CAMIM_BASE}/token"
USERINFO_URL   = f"{CAMIM_BASE}/me"

User = get_user_model()


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
        "scope":         "openid profile email",
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
            verify=False,
        )
        logger.error("CAMIM /me status=%s body=%s", user_resp.status_code, user_resp.text[:500])
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

    # ── Busca ou cria o usuário pelo e-mail ──────────────────────
    name       = (userinfo.get("name") or "").strip()
    first_name = (userinfo.get("given_name") or name.split()[0] if name else "").strip()
    last_name  = (userinfo.get("family_name") or " ".join(name.split()[1:]) if name else "").strip()

    try:
        user = User.objects.get(email__iexact=email)
    except User.DoesNotExist:
        # Primeira vez: cria conta sem senha (só acessa via IDCamim)
        username = email.split("@")[0]
        # Garante username único
        base_username = username
        counter = 1
        while User.objects.filter(username=username).exists():
            username = f"{base_username}{counter}"
            counter += 1
        user = User.objects.create_user(
            username=username,
            email=email,
            first_name=first_name,
            last_name=last_name,
            password=None,  # sem senha — login só via IDCamim
        )
    except User.MultipleObjectsReturned:
        user = User.objects.filter(email__iexact=email).order_by("id").first()

    if not user.is_active:
        messages.error(request, "Sua conta está inativa. Fale com o administrador.")
        return redirect("boards:login")

    # ── Loga o usuário ────────────────────────────────────────────
    login(request, user, backend="boards.auth_backends.UsernameOrEmailBackend")

    next_url = request.session.pop("camim_next", "/")
    # Garante que o next é seguro (mesma origem)
    if not next_url or not next_url.startswith("/"):
        next_url = "/"

    return redirect(next_url)
