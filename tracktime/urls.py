# tracktime/urls.py
from django.urls import path
from . import views

app_name = "tracktime"

urlpatterns = [
    # painel do card
    path("cards/<int:card_id>/track-time/", views.card_tracktime_panel, name="card_panel"),
    path("me/running.json", views.me_running_json, name="me_running_json"),

    # ações
    path("cards/<int:card_id>/track-time/start/", views.card_tracktime_start, name="card_start"),
    path("cards/<int:card_id>/track-time/stop/", views.card_tracktime_stop, name="card_stop"),
    path("cards/<int:card_id>/track-time/manual/", views.card_tracktime_manual, name="card_manual"),

    # confirmação (+1h)
    path("cards/<int:card_id>/track-time/confirm/", views.card_tracktime_confirm_extend, name="card_confirm_extend"),
    path("confirm/<int:entry_id>/<str:token>/", views.tracktime_confirm_link, name="confirm_link"),

    # portal
    path("", views.portal, name="portal"),
    path("projects/<int:pk>/toggle/", views.toggle_project, name="toggle_project"),
    path("activities/<int:pk>/toggle/", views.toggle_activity, name="toggle_activity"),
    path("boards/<int:board_id>/running/", views.board_running, name="board_running"),

    # Modal Track-time
    path("modal/", views.tracktime_modal, name="modal"),
    path("cards/<int:card_id>/track-time/running-slot/", views.card_tracktime_panel_running_slot, name="card_panel_running_slot"),
    path("cards/<int:card_id>/track-time/elapsed.json", views.card_elapsed_json, name="card_elapsed_json"),

    # ✅ NOVO: telefone obrigatório (modal + save)
    path("phone/required-modal/", views.tracktime_phone_required_modal, name="phone_required_modal"),
    path("phone/save/", views.tracktime_phone_save, name="phone_save"),

    # Tabs (HTML)
    path("tabs/live/", views.tracktime_tab_live, name="tab_live"),
    path("tabs/portal/", views.tracktime_tab_portal, name="tab_portal"),
    path("tabs/week/", views.tracktime_tab_week, name="tab_week"),
    path("tabs/month/", views.tracktime_tab_month, name="tab_month"),

    # Dados (JSON) para polling do “Ao vivo”
    path("live.json", views.tracktime_live_json, name="live_json"),
]
