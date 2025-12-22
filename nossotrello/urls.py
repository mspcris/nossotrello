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
from django.contrib import admin
from django.urls import path, include

from django.conf import settings
from django.conf.urls.static import static

from boards import views as boards_views

urlpatterns = [
    # PRIMEIRO LOGIN (auto-provisionamento + email de definir senha)
    path("accounts/first-login/", boards_views.first_login, name="first_login"),

    # AUTH padrão do Django: login/logout/password_reset/...
    path("accounts/", include("django.contrib.auth.urls")),

    path("admin/", admin.site.urls),
    path("", include("boards.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

