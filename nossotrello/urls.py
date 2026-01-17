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

urlpatterns = [
    # Admin
    path("admin/", admin.site.urls),

    # App principal (boards nossotrello)
    path("", include(("boards.urls", "boards"), namespace="boards")),

    # =========================================================
    # QA / CHECKLIST (NÃO linkado em lugar nenhum)
    # =========================================================
    path(
        "qa/checktrello/",
        TemplateView.as_view(template_name="checktrello.html"),
        name="qa_checktrello",
    ),

    # App tracktime
    path("", include(("boards.urls", "boards"), namespace="boards")),
    path("track-time/", include(("tracktime.urls", "tracktime"), namespace="tracktime")),



]

# Media em desenvolvimento
if settings.DEBUG:
    urlpatterns += static(
        settings.MEDIA_URL,
        document_root=settings.MEDIA_ROOT
    )

    path("", include(("boards.urls", "boards"), namespace="boards")),
    