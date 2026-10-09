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
from .campaigns import (
    CAMPAIGN_EMAIL_JOB,
    refresh_campaign_delivery_status,
    send_campaign_email,
)
from .models import CampaignRecipient


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


def send_campaign_email_job(job):
    recipient = CampaignRecipient.objects.select_related(
        "campaign__tenant__brand",
        "customer",
    ).get(
        pk=job.payload["campaign_recipient_id"],
        tenant=job.tenant,
    )
    if recipient.status == CampaignRecipient.Status.SENT:
        return recipient
    recipient.status = CampaignRecipient.Status.SENDING
    recipient.error_code = ""
    recipient.save(update_fields=("status", "error_code", "updated_at"))
    refresh_campaign_delivery_status(recipient.campaign_id)
    delivery, should_send = begin_email_delivery(
        job=job,
        customer=recipient.customer,
        subject=recipient.campaign.subject,
        generation=1,
        template_key=f"email-campaign-{recipient.campaign_id}-v1",
    )
    if not should_send:
        recipient.status = CampaignRecipient.Status.SENT
        recipient.sent_at = delivery.completed_at or delivery.started_at
        recipient.save(update_fields=("status", "sent_at", "updated_at"))
        refresh_campaign_delivery_status(recipient.campaign_id)
        return recipient
    try:
        sent = send_campaign_email(recipient)
        if not sent:
            raise RuntimeError("Email backend returned no delivery confirmation.")
    except Exception as exc:
        mark_email_delivery_unknown(delivery)
        recipient.status = CampaignRecipient.Status.FAILED
        recipient.error_code = "email_delivery_outcome_unknown"
        recipient.save(update_fields=("status", "error_code", "updated_at"))
        refresh_campaign_delivery_status(recipient.campaign_id)
        raise IntegrationError(
            "Campaign email delivery outcome is unknown.",
            error_code="email_delivery_outcome_unknown",
        ) from exc
    delivery = mark_email_delivery_sent(delivery)
    recipient.status = CampaignRecipient.Status.SENT
    recipient.sent_at = delivery.completed_at
    recipient.save(update_fields=("status", "sent_at", "updated_at"))
    refresh_campaign_delivery_status(recipient.campaign_id)
    return recipient


register_job_handler(CAMPAIGN_EMAIL_JOB, send_campaign_email_job)


__all__ = [
    "CAMPAIGN_EMAIL_JOB",
    "EMAIL_JOB",
    "send_campaign_email_job",
    "send_pass_email_job",
]
