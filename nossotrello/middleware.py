# nossotrello/middleware.py
from django.conf import settings
from django.shortcuts import redirect
from django.utils.http import urlencode


# URLs que ficam isentas de todos os checks (auth, termos, cookies)
_ALWAYS_FREE = [
    "/accounts/",
    "/admin/",
    "/legal/",        # termos, privacidade, cookies, manual
    "/cookies/",      # aceitar/rejeitar cookies via POST
]


class LoginRequiredMiddleware:
    """
    Força autenticação para todas as rotas, exceto as listadas em _ALWAYS_FREE.
    """

    def __init__(self, get_response):
        self.get_response = get_response
        self.login_url = getattr(settings, "LOGIN_URL", "/accounts/login/")

    def __call__(self, request):
        path = request.path or "/"

        if any(path.startswith(p) for p in _ALWAYS_FREE):
            return self.get_response(request)

        if settings.DEBUG and (path.startswith("/static/") or path.startswith("/media/")):
            return self.get_response(request)

        if not request.user.is_authenticated:
            query = urlencode({"next": path})
            return redirect(f"{self.login_url}?{query}")

        return self.get_response(request)


class TermsMiddleware:
    """
    Se o usuário autenticado ainda não aceitou os Termos de Uso,
    redireciona para /legal/termos/?next=<url_original>.
    """

    from boards.views.legal import CURRENT_TERMS_VERSION as _CURRENT

    _TERMS_URL = "/legal/termos/"

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path or "/"

        # Isenta rotas públicas/legais
        if any(path.startswith(p) for p in _ALWAYS_FREE):
            return self.get_response(request)

        if settings.DEBUG and (path.startswith("/static/") or path.startswith("/media/")):
            return self.get_response(request)

        if not request.user.is_authenticated:
            return self.get_response(request)

        # Verifica aceite dos termos
        profile = getattr(request.user, "profile", None)
        if profile is not None:
            accepted = bool(getattr(profile, "terms_accepted", False))
            version_ok = getattr(profile, "terms_version", "") == self._CURRENT
            if not accepted or not version_ok:
                if path != self._TERMS_URL:
                    query = urlencode({"next": path})
                    return redirect(f"{self._TERMS_URL}?{query}")

        return self.get_response(request)
