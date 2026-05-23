# boards/views/legal.py
from urllib.parse import urlparse

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render, redirect
from django.utils import timezone
from django.views.decorators.http import require_POST

# Versão corrente dos termos — incrementar aqui força re-aceite de todos
CURRENT_TERMS_VERSION = "2.0"


def _get_client_ip(request):
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    return xff.split(",")[0].strip() if xff else request.META.get("REMOTE_ADDR")


def _safe_next(value: str) -> str:
    """Aceita só URLs internas relativas (começa com '/' mas não '//' nem '/\\').
    Anti open-redirect."""
    if not value:
        return ""
    value = value.strip()
    if not value.startswith("/"):
        return ""
    if value.startswith("//") or value.startswith("/\\"):
        return ""
    return value


def _referer_path(request) -> str:
    """Extrai path+query do Referer SE for do mesmo host. Caso contrário ''."""
    ref = (request.META.get("HTTP_REFERER") or "").strip()
    if not ref:
        return ""
    try:
        parsed = urlparse(ref)
    except Exception:
        return ""
    host_req = (request.get_host() or "").lower()
    host_ref = (parsed.netloc or "").lower()
    if host_ref and host_ref != host_req:
        return ""
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    # Não retornar a própria página de termos como next
    if path.startswith("/legal/termos"):
        return ""
    return _safe_next(path)


@login_required
def terms_view(request):
    """
    GET  → se NÃO aceitou a versão atual: overlay com checkboxes + Continuar
           se JÁ aceitou: modo consulta (texto + selo "Aceito em X" + histórico)
    POST → registra novo aceite e redireciona para `next` (ou Referer ou raiz)
    """
    # next vem por (1) ?next=, (2) hidden input do form, (3) Referer (se mesma origem)
    next_url = (
        _safe_next(request.GET.get("next") or "")
        or _safe_next(request.POST.get("next") or "")
        or _referer_path(request)
        or "/"
    )

    profile = getattr(request.user, "profile", None)
    already_accepted = bool(
        profile
        and getattr(profile, "terms_accepted", False)
        and getattr(profile, "terms_version", "") == CURRENT_TERMS_VERSION
    )

    if request.method == "POST":
        accept = request.POST.get("accept") == "1"
        cookies = request.POST.get("cookies_accept") == "1"

        if not accept:
            return render(request, "legal/terms.html", {
                "next_url": next_url,
                "error": "Você precisa aceitar os Termos de Uso para continuar.",
                "already_accepted": already_accepted,
                "current_version": CURRENT_TERMS_VERSION,
                "acceptance_history": _user_acceptance_history(request.user),
            })

        if profile is not None:
            profile.terms_accepted = True
            profile.terms_accepted_at = timezone.now()
            profile.terms_version = CURRENT_TERMS_VERSION
            profile.save(update_fields=["terms_accepted", "terms_accepted_at", "terms_version"])

        # Log de auditoria imutável
        from boards.models import TermsAcceptanceLog
        TermsAcceptanceLog.objects.create(
            user=request.user,
            version=CURRENT_TERMS_VERSION,
            ip_address=_get_client_ip(request),
            user_agent=request.META.get("HTTP_USER_AGENT", "")[:500],
            cookies_accepted=cookies,
        )

        response = redirect(next_url)

        if cookies:
            response.set_cookie(
                "cookies_accepted",
                "1",
                max_age=60 * 60 * 24 * 365,
                httponly=False,
                samesite="Lax",
            )

        return response

    return render(request, "legal/terms.html", {
        "next_url": next_url,
        "already_accepted": already_accepted,
        "current_version": CURRENT_TERMS_VERSION,
        "acceptance_history": _user_acceptance_history(request.user),
    })


def _user_acceptance_history(user):
    """Retorna lista de TermsAcceptanceLog do usuário, mais recente primeiro."""
    from boards.models import TermsAcceptanceLog
    return list(
        TermsAcceptanceLog.objects
        .filter(user=user)
        .order_by("-accepted_at")[:50]
    )


def privacy_view(request):
    """Política de Privacidade — pública (não requer login)."""
    return render(request, "legal/privacy.html")


def cookie_policy_view(request):
    """Política de Cookies — pública."""
    return render(request, "legal/cookies.html")


def manual_view(request):
    """Manual do usuário — pública."""
    return render(request, "legal/manual.html")


@require_POST
def cookie_accept_view(request):
    """
    Aceita cookies via AJAX (barra de cookies no rodapé).
    Usado por usuários que JÁ aceitaram termos mas ainda não aceitaram cookies.
    """
    response = JsonResponse({"ok": True})
    response.set_cookie(
        "cookies_accepted",
        "1",
        max_age=60 * 60 * 24 * 365,
        httponly=False,
        samesite="Lax",
    )
    return response


@require_POST
def cookie_reject_view(request):
    """Rejeita cookies — mantém apenas os essenciais (sessão)."""
    # Não define cookie: a barra permanece visível + site fica bloqueado
    return JsonResponse({"ok": True, "rejected": True})
