"""
Roteamento WebSocket do app boards.

Importado por `nossotrello/asgi.py` para compor o router ASGI.
Adicione novos consumers aqui conforme forem sendo criados.
"""

from django.urls import re_path

from . import consumers

websocket_urlpatterns = [
    # Canal por board — recebe eventos granulares (cards, unread, access, track-time)
    re_path(
        r"^ws/board/(?P<board_id>\d+)/$",
        consumers.BoardConsumer.as_asgi(),
    ),
    # Canal pessoal do usuário — notificações, chat badge, track-time próprio
    re_path(
        r"^ws/me/$",
        consumers.UserConsumer.as_asgi(),
    ),
]
