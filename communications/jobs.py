"""Durable handlers for platform email jobs."""

from django.conf import settings

from customers.models import Customer
from integrations.contracts import IntegrationError, RetryableIntegrationError
from integrations.models import IntegrationConnection
from integrations.registry import register_job_handler

from .registry import email_application_context
from .services import (
    begin_email_delivery,
    customer_apple_pass,
    email_subject_for,
    mark_email_delivery_sent,
    mark_email_delivery_unknown,
    send_pass_email,
)


EMAIL_JOB = "communications.email.pass"


def send_pass_email_job(job):
    customer = Customer.objects.get(
        pk=job.payload["customer_id"], tenant=job.tenant
    )
    google_enabled = IntegrationConnection.objects.filter(
        tenant=job.tenant,
        provider=IntegrationConnection.Provider.GOOGLE_WALLET,
        enabled=True,
    ).exists()
    if google_enabled and not customer.google_jwt_url:
        raise RetryableIntegrationError(
            error_code="google_wallet_pending", retry_after=10
        )
    apple_enabled = bool(
        settings.APPLE_WALLET_PASS_TYPE_IDENTIFIER
        and settings.APPLE_WALLET_TEAM_IDENTIFIER
    )
    if apple_enabled and not customer_apple_pass(customer, create_identity=False).is_file():
        raise RetryableIntegrationError(
            error_code="wallet_artifact_pending", retry_after=10
        )
    context = email_application_context(job)
    delivery, should_send = begin_email_delivery(
        job=job,
        customer=customer,
        subject=email_subject_for(customer, context.brand_snapshot),
        generation=context.generation,
    )
    if not should_send:
        return delivery
    try:
        sent = send_pass_email(
            customer,
            brand_snapshot=context.brand_snapshot,
            application_link_url=context.application_link_url,
            require_apple=apple_enabled,
        )
        if not sent:
            raise RuntimeError("Email backend returned no delivery confirmation.")
    except Exception as exc:
        mark_email_delivery_unknown(delivery)
        raise IntegrationError(
            "Email delivery outcome is unknown; use explicit resend.",
            error_code="email_delivery_outcome_unknown",
        ) from exc
    return mark_email_delivery_sent(delivery)


register_job_handler(EMAIL_JOB, send_pass_email_job)


__all__ = ["EMAIL_JOB", "send_pass_email_job"]
