from django.conf import settings
from django.conf.urls.static import static
from django.urls import path

from . import views

app_name = "dotykacka"

urlpatterns = [
    path("acces_token", views.get_acces_token, name="acces_token"),
    path("customers", views.get_all_costumers, name="customers"),
    path("register", views.register_customer_form, name="register"),
    path(
        "c/<slug:tenant_slug>/register",
        views.register_customer_form,
        name="tenant_register",
    ),
    path(
        "c/<slug:tenant_slug>/portal",
        views.tenant_portal,
        name="tenant_portal",
    ),
    path(
        "c/<slug:tenant_slug>/settings/integrations",
        views.integration_settings,
        name="integration_settings",
    ),
    path(
        "c/<slug:tenant_slug>/settings/card-design",
        views.card_design_settings,
        name="card_design_settings",
    ),
    path(
        "c/<slug:tenant_slug>/artifacts/<int:artifact_id>/download",
        views.card_artifact_download,
        name="card_artifact_download",
    ),
    path(
        "platform/print-center",
        views.platform_print_center,
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

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
