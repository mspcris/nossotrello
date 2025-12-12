from django.conf import settings
from django.shortcuts import redirect
from django.utils.http import urlencode


class LoginRequiredMiddleware:
    """
    Força autenticação para todas as rotas, exceto:
    - /accounts/ (login/logout/password reset)
    - /admin/
    - /static/ e /media/ (quando DEBUG)
    """

    def __init__(self, get_response):
        self.get_response = get_response

        self.exempt_prefixes = [
            "/accounts/",
            "/admin/",
        ]

        # fallback seguro
        self.login_url = getattr(settings, "LOGIN_URL", "/accounts/login/")

    def __call__(self, request):
        path = request.path or "/"

        # libera rotas de autenticação e admin
        if any(path.startswith(p) for p in self.exempt_prefixes):
            return self.get_response(request)

        # libera estáticos e mídia em dev
        if settings.DEBUG and (path.startswith("/static/") or path.startswith("/media/")):
            return self.get_response(request)

        # se não está autenticado, redireciona pro login com next=
        if not request.user.is_authenticated:
            query = urlencode({"next": path})
            return redirect(f"{self.login_url}?{query}")

        return self.get_response(request)
