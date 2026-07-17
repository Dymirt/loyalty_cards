"""Subscription, quote, and platform-commercial routes."""

from django.urls import path

from . import views


app_name = "billing"
urlpatterns = [
    path("c/<slug:tenant_slug>/billing", views.tenant_billing, name="tenant"),
    path(
        "c/<slug:tenant_slug>/billing/quotes",
        views.create_quote,
        name="create_quote",
    ),
    path(
        "c/<slug:tenant_slug>/billing/quotes/<int:quote_id>/accept",
        views.accept_tenant_quote,
        name="accept_quote",
    ),
    path("platform/billing", views.platform_billing, name="platform"),
]
