# boards/views/legal.py
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


@login_required
def terms_view(request):
    """
    GET  → exibe overlay com Termos de Uso.
    POST → registra aceite e redireciona para `next` (ou raiz).
    """
    next_url = request.GET.get("next") or request.POST.get("next") or "/"

    if request.method == "POST":
        accept = request.POST.get("accept") == "1"
        cookies = request.POST.get("cookies_accept") == "1"

        if not accept:
            return render(request, "legal/terms.html", {
                "next_url": next_url,
                "error": "Você precisa aceitar os Termos de Uso para continuar.",
            })

        # Marca aceite no perfil
        profile = getattr(request.user, "profile", None)
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
                max_age=60 * 60 * 24 * 365,  # 1 ano
                httponly=False,
                samesite="Lax",
            )

        return response

    return render(request, "legal/terms.html", {"next_url": next_url})


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
