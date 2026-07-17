"""Owner-only integration settings and status routes."""

from django.urls import path

from . import views


app_name = "integrations"

urlpatterns = [
    path(
        "platform/system-connections",
        views.system_connections,
        name="system_connections",
    ),
    path(
        "platform/system-connections/<slug:key>/test",
        views.test_system_connection,
        name="test_system_connection",
    ),
    path(
        "c/<slug:tenant_slug>/settings/integrations",
        views.integration_settings,
        name="settings",
    ),
    path(
        "c/<slug:tenant_slug>/settings/integrations/<slug:provider>/test",
        views.test_integration,
        name="test",
    ),
]
