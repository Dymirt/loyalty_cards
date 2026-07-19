"""Tenant print-request and platform production routes."""

from django.urls import path

from . import views


app_name = "printing"
urlpatterns = [
    path("c/<slug:tenant_slug>/printing", views.tenant_printing, name="tenant"),
    path(
        "c/<slug:tenant_slug>/printing/requests",
        views.submit_request,
        name="submit",
    ),
    path("platform/print-center", views.platform_print_center, name="platform_queue"),
    path(
        "platform/print-center/requests/<int:request_id>",
        views.platform_request_detail,
        name="platform_detail",
    ),
    path(
        "platform/print-center/requests/<int:request_id>/approve",
        views.approve_request,
        name="approve",
    ),
    path(
        "platform/print-center/requests/<int:request_id>/reject",
        views.reject_request,
        name="reject",
    ),
    path(
        "platform/print-center/requests/<int:request_id>/allocate",
        views.allocate_request,
        name="allocate",
    ),
    path(
        "platform/print-center/requests/<int:request_id>/cancel",
        views.cancel_request,
        name="cancel",
    ),
    path(
        "platform/print-center/requests/<int:request_id>/fulfillment",
        views.fulfill_request,
        name="fulfill",
    ),
    path(
        "platform/print-center/requests/<int:request_id>/status",
        views.run_status,
        name="run_status",
    ),
    path(
        "platform/print-center/packages/<int:package_id>/download",
        views.package_download,
        name="package_download",
    ),
    path(
        "platform/print-center/fulfillment/<int:event_id>/correct",
        views.correct_event,
        name="correct_event",
    ),
    path(
        "platform/print-center/legacy/preview",
        views.legacy_preview,
        name="legacy_preview",
    ),
    path(
        "platform/print-center/legacy/confirm",
        views.legacy_confirm,
        name="legacy_confirm",
    ),
]
