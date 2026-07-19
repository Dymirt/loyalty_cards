from django.urls import path

from . import views


app_name = "enrollment"
urlpatterns = [
    path("register", views.register_customer_form, name="register"),
    path("c/<slug:tenant_slug>/register", views.register_customer_form, name="tenant_register"),
    path("enrollment/status/<str:token>", views.public_status, name="public_status"),
    path(
        "enrollment/status/<str:token>/apple-pass",
        views.public_apple_pass,
        name="public_apple_pass",
    ),
    path(
        "c/<slug:tenant_slug>/enrollments",
        views.tenant_enrollments,
        name="manage",
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
