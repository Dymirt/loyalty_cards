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
    path(
        "c/<slug:tenant_slug>/artwork-sources/<int:source_id>/preview",
        views.card_artwork_source_preview,
        name="source_preview",
    ),
]
