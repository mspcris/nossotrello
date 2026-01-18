from django.urls import path
from . import views

app_name = "tracktime"

urlpatterns = [
    # painel do card
    path("cards/<int:card_id>/track-time/", views.card_tracktime_panel, name="card_panel"),

    # ações
    path("cards/<int:card_id>/track-time/start/", views.card_tracktime_start, name="card_start"),
    path("cards/<int:card_id>/track-time/stop/", views.card_tracktime_stop, name="card_stop"),
    path("cards/<int:card_id>/track-time/manual/", views.card_tracktime_manual, name="card_manual"),
    path("", views.portal, name="portal"),
    path("projects/<int:pk>/toggle/", views.toggle_project, name="toggle_project"),
    path("activities/<int:pk>/toggle/", views.toggle_activity, name="toggle_activity"),

]
