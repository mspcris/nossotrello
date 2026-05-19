"""
URL configuration for nossotrello project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
"""URL configuration for nossotrello project."""
# nossotrello/urls.py

from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic import TemplateView

from boards.views.legal import (
    terms_view,
    privacy_view,
    cookie_policy_view,
    manual_view,
    cookie_accept_view,
    cookie_reject_view,
)
from boards.views.media_serve import serve_stored_file
from nossotrello.error_views import server_error as custom_500

# Página custom de erro 500 (byte_maze) — usada pelo Django quando uma
# request resulta em exception não-tratada.
handler500 = "nossotrello.error_views.server_error"

urlpatterns = [
    path("admin/", admin.site.urls),

    # Endpoint de teste pra abrir a mesma página 500 sem precisar forçar
    # um crash. Retorna status 500 com o HTML do template 500.html.
    path("500/", custom_500, name="test_500"),

    # ── Legal (isento de termos/cookies no middleware) ──────────────
    path("legal/termos/",      terms_view,         name="terms"),
    path("legal/privacidade/", privacy_view,        name="privacy"),
    path("legal/cookies/",     cookie_policy_view,  name="cookie_policy"),
    path("legal/manual/",      manual_view,         name="manual"),
    path("cookies/accept/",    cookie_accept_view,  name="cookie_accept"),
    path("cookies/reject/",    cookie_reject_view,  name="cookie_reject"),

    # App principal
    path("", include(("boards.urls", "boards"), namespace="boards")),

    # QA / CHECKLIST
    path(
        "qa/checktrello/",
        TemplateView.as_view(template_name="checktrello.html"),
        name="qa_checktrello",
    ),

    # Tracktime
    path("track-time/", include(("tracktime.urls", "tracktime"), namespace="tracktime")),

    # API mobile (REST — rotas 100% novas, sem tocar nas existentes)
    path("api/mobile/", include(("api_mobile.urls", "api_mobile"), namespace="api_mobile")),
]

# Serving de arquivos do banco (StoredFile) e referencias legadas
urlpatterns += [
    path("media/serve/<path:file_ref>/", serve_stored_file, name="serve_stored_file"),
]

# Fallback: serve arquivos do filesystem (migração gradual / dev)
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
# END nossotrello/urls.py
