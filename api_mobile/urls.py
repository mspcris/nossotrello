# api_mobile/urls.py
"""URLs REST para o app mobile — prefixo /api/mobile/"""

from django.urls import path
from . import views

app_name = "api_mobile"

urlpatterns = [
    # ── Auth ─────────────────────────────────────────────────────
    path("auth/login/", views.api_login, name="login"),
    path("auth/login-camim/", views.api_login_camim, name="login_camim"),
    path("auth/logout/", views.api_logout, name="logout"),

    # ── Profile ──────────────────────────────────────────────────
    path("me/", views.api_me, name="me"),
    path("me/update/", views.api_me_update, name="me_update"),

    # ── Boards ───────────────────────────────────────────────────
    path("boards/", views.api_boards, name="boards"),
    path("boards/<int:board_id>/", views.api_board_detail, name="board_detail"),

    # ── Cards ────────────────────────────────────────────────────
    path("cards/<int:card_id>/", views.api_card_detail, name="card_detail"),
    path("cards/<int:card_id>/update/", views.api_card_update, name="card_update"),
    path("cards/<int:card_id>/move/", views.api_card_move, name="card_move"),
    path("cards/<int:card_id>/activity/", views.api_card_activity, name="card_activity"),
    path("cards/<int:card_id>/comment/", views.api_card_comment, name="card_comment"),
    path("columns/<int:column_id>/cards/", views.api_card_create, name="card_create"),

    # ── Checklists ───────────────────────────────────────────────
    path("checklist-items/<int:item_id>/toggle/", views.api_checklist_toggle, name="checklist_toggle"),

    # ── Social ───────────────────────────────────────────────────
    path("social/feed/", views.api_social_feed, name="social_feed"),
    path("social/posts/", views.api_social_post_create, name="social_post_create"),
    path("social/posts/<int:post_id>/react/", views.api_social_react, name="social_react"),
    path("social/posts/<int:post_id>/comments/", views.api_social_comments, name="social_comments"),
    path("social/posts/<int:post_id>/comments/add/", views.api_social_comment_create, name="social_comment_create"),

    # ── Chat ─────────────────────────────────────────────────────
    path("chat/", views.api_chat_conversations, name="chat_conversations"),
    path("chat/<int:conversation_id>/messages/", views.api_chat_messages, name="chat_messages"),
    path("chat/<int:conversation_id>/send/", views.api_chat_send, name="chat_send"),

    # ── Daily Check-in ───────────────────────────────────────────
    path("checkin/", views.api_daily_checkin, name="daily_checkin"),

    # ── Notifications / Mentions ─────────────────────────────────
    path("notifications/", views.api_notifications, name="notifications"),
    path("mentions/", views.api_mentions, name="mentions"),
    path("mentions/mark-seen/", views.api_mentions_mark_seen, name="mentions_mark_seen"),

    # ── Search ───────────────────────────────────────────────────
    path("search/", views.api_search, name="search"),

    # ── Saúde e Bem Estar ────────────────────────────────────────
    path("health/analyze/", views.api_health_analyze, name="health_analyze"),
    path("health/chat/", views.api_health_chat, name="health_chat"),

    # ── Camila News ──────────────────────────────────────────────
    path("camila/news/", views.api_camila_news, name="camila_news"),
]
