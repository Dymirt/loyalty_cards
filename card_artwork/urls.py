from django.urls import path

from . import views


app_name = "card_artwork"
urlpatterns = [
    path(
        "c/<slug:tenant_slug>/settings/card-design",
        views.card_design_settings,
        name="settings",
    ),
    path(
        "c/<slug:tenant_slug>/artifacts/<int:artifact_id>/download",
        views.card_artifact_download,
        name="artifact_download",
    ),
]
