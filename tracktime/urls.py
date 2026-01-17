from django.urls import path
from . import views

app_name = "tracktime"

urlpatterns = [
    path("", views.portal, name="portal"),

    # card modal
    path(
        "cards/<int:card_id>/track-time/",
        views.card_tracktime_panel,
        name="card_panel",
    ),
    path(
        "cards/<int:card_id>/track-time/manual/",
        views.card_tracktime_manual,
        name="card_manual",
    ),
]
