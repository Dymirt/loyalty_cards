"""Durable handlers for platform email jobs."""

from customers.models import Customer
from integrations.contracts import RetryableIntegrationError
from integrations.models import IntegrationConnection
from integrations.registry import register_job_handler

from .services import send_pass_email


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
    try:
        return send_pass_email(customer)
    except FileNotFoundError as exc:
        raise RetryableIntegrationError(
            error_code="wallet_artifact_pending", retry_after=10
        ) from exc


register_job_handler(EMAIL_JOB, send_pass_email_job)


__all__ = ["EMAIL_JOB", "send_pass_email_job"]
