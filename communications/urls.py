"""Tenant campaign URLs."""

from django.urls import path

from . import views


app_name = "communications"
urlpatterns = [
    path(
        "c/<slug:tenant_slug>/communications",
        views.campaign_list,
        name="list",
    ),
    path(
        "c/<slug:tenant_slug>/communications/new",
        views.campaign_compose,
        name="new",
    ),
    path(
        "c/<slug:tenant_slug>/communications/<int:campaign_id>",
        views.campaign_compose,
        name="edit",
    ),
    path(
        "c/<slug:tenant_slug>/communications/<int:campaign_id>/preview",
        views.campaign_preview,
        name="preview",
    ),
    path(
        "c/<slug:tenant_slug>/communications/<int:campaign_id>/assets/<int:asset_id>",
        views.campaign_asset,
        name="asset",
    ),
]
