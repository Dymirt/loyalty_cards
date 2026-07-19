from django.urls import path

from . import views
from card_artwork.views import card_artifact_download, card_design_settings
from printing.views import platform_print_center
from customers.views import get_all_customers
from enrollment.views import register_customer_form
from integrations.views import integration_settings
from tenants.views import tenant_portal

app_name = "dotykacka"

urlpatterns = [
    path("acces_token", views.get_acces_token, name="acces_token"),
    path("customers", get_all_customers, name="customers"),
    path("register", register_customer_form, name="register"),
    path(
        "c/<slug:tenant_slug>/register",
        register_customer_form,
        name="tenant_register",
    ),
    path(
        "c/<slug:tenant_slug>/portal",
        tenant_portal,
        name="tenant_portal",
    ),
    path(
        "c/<slug:tenant_slug>/settings/integrations",
        integration_settings,
        name="integration_settings",
    ),
    path(
        "c/<slug:tenant_slug>/settings/card-design",
        card_design_settings,
        name="card_design_settings",
    ),
    path(
        "c/<slug:tenant_slug>/artifacts/<int:artifact_id>/download",
        card_artifact_download,
        name="card_artifact_download",
    ),
    path(
        "platform/print-center",
        platform_print_center,
        name="platform_print_center",
    ),
    path("send_pass/<str:barcode>", views.send_pass, name="send_pass"),
    path("add_all_to_brevo", views.add_all_to_brevo, name="add_all_to_brevo"),
    path(
        "generate_jwt_passes",
        views.generate_jwt_passes,
        name="generate_jwt_passes",
    ),
    path("send_passes_to_all", views.send_all_passes, name="send_passes_to_all"),
]
