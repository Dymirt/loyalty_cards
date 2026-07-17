"""Dotykačka Connector v2 browser flow."""

from django.urls import path

from . import views


app_name = "pos_dotykacka"

urlpatterns = [
    path(
        "dotykacka/<slug:tenant_slug>/connect",
        views.connect_dotykacka,
        name="connect",
    ),
    path(
        "dotykacka/<slug:tenant_slug>/disconnect",
        views.disconnect_dotykacka,
        name="disconnect",
    ),
    path("dotykacka/callback", views.dotykacka_callback, name="callback"),
]
