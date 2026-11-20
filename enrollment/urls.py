from django.urls import path

from . import views


app_name = "enrollment"
urlpatterns = [
    path("register", views.register_customer_form, name="register"),
    path("c/<slug:tenant_slug>/register", views.register_customer_form, name="tenant_register"),
    path(
        "c/<slug:tenant_slug>/virtual-card",
        views.virtual_card_form,
        name="virtual_card_form",
    ),
    path(
        "c/<slug:tenant_slug>/virtual-card/designs/<int:design_id>/<str:asset_kind>",
        views.virtual_card_design_asset,
        name="virtual_card_design_asset",
    ),
    path("enrollment/status/<str:token>", views.public_status, name="public_status"),
    path(
        "enrollment/status/<str:token>/apple-pass",
        views.public_apple_pass,
        name="public_apple_pass",
    ),
    path(
        "virtual-card/wallet/<str:token>/apple-pass",
        views.public_virtual_apple_pass,
        name="public_virtual_apple_pass",
    ),
    path(
        "c/<slug:tenant_slug>/enrollments",
        views.tenant_enrollments,
        name="manage",
    ),
    path(
        "c/<slug:tenant_slug>/settings/virtual-card-api",
        views.virtual_card_api_keys,
        name="virtual_card_api_keys",
    ),
    path(
        "c/<slug:tenant_slug>/settings/virtual-card-api/<int:key_id>/revoke",
        views.revoke_virtual_card_api_key,
        name="revoke_virtual_card_api_key",
    ),
    path(
        "c/<slug:tenant_slug>/enrollments/domain",
        views.request_domain,
        name="request_domain",
    ),
    path(
        "c/<slug:tenant_slug>/enrollments/<int:enrollment_id>",
        views.enrollment_detail,
        name="detail",
    ),
    path(
        "c/<slug:tenant_slug>/enrollments/<int:enrollment_id>/ensure",
        views.ensure_followups,
        name="ensure_followups",
    ),
    path(
        "c/<slug:tenant_slug>/enrollments/<int:enrollment_id>/resend-email",
        views.resend_email,
        name="resend_email",
    ),
    path(
        "c/<slug:tenant_slug>/enrollments/followups/<int:followup_id>/retry",
        views.retry_followup,
        name="retry_followup",
    ),
]
