"""
ASGI config for nossotrello project.

Expõe a callable ASGI `application`, que o Daphne usa para servir tanto HTTP
quanto WebSocket. O roteamento WebSocket vai para `boards.routing.websocket_urlpatterns`.

O Gunicorn WSGI continua servindo HTTP em produção; o Daphne é um processo
paralelo dedicado exclusivamente ao tráfego `/ws/`. Veja docker-compose.yml.
"""

import os

from dotenv import load_dotenv

# carrega .env ANTES de importar qualquer coisa que leia settings
load_dotenv()
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "nossotrello.settings")

# Django precisa ser inicializado antes de importar qualquer consumer
import django  # noqa: E402
django.setup()

from channels.auth import AuthMiddlewareStack  # noqa: E402
from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402
from channels.security.websocket import AllowedHostsOriginValidator  # noqa: E402
from django.core.asgi import get_asgi_application  # noqa: E402

# Importa as rotas WS depois do django.setup() para evitar AppRegistryNotReady
from boards.routing import websocket_urlpatterns  # noqa: E402


django_asgi_app = get_asgi_application()

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": AllowedHostsOriginValidator(
            AuthMiddlewareStack(URLRouter(websocket_urlpatterns))
        ),
    }
)
