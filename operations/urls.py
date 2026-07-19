from django.urls import path

from . import views


app_name = "operations"

urlpatterns = [
    path("platform/operations", views.dashboard, name="dashboard"),
    path(
        "platform/operations/alerts/<uuid:alert_id>/acknowledge",
        views.acknowledge,
        name="acknowledge",
    ),
    path(
        "platform/operations/alerts/<uuid:alert_id>/resolve",
        views.resolve,
        name="resolve",
    ),
]
