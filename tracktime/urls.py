from django.urls import path
from . import views

app_name = "tracktime"

urlpatterns = [
    path("", views.portal, name="portal"),
]
