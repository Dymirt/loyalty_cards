"""Durable Dotykačka customer-upsert handler."""

from django.utils import timezone

from customers.models import Customer, CustomerExternalIdentity
from integrations.contracts import RetryableIntegrationError
from integrations.registry import register_job_handler

from .services import PROVIDER, adapter_for_tenant


CUSTOMER_UPSERT_JOB = "pos.dotykacka.customer_upsert"


def upsert_customer_job(job):
    customer = Customer.objects.get(
        pk=job.payload["customer_id"], tenant=job.tenant
    )
    try:
        return adapter_for_tenant(job.tenant).upsert_customer(customer)
    except Exception as exc:
        retry_pending = (
            isinstance(exc, RetryableIntegrationError)
            and job.attempts < job.max_attempts
        )
        identity, _ = CustomerExternalIdentity.objects.get_or_create(
            tenant=customer.tenant,
            customer=customer,
            provider=PROVIDER,
        )
        identity.sync_status = (
            CustomerExternalIdentity.SyncStatus.PENDING
            if retry_pending
            else CustomerExternalIdentity.SyncStatus.FAILED
        )
        identity.last_attempted_at = timezone.now()
        identity.last_error_code = getattr(
            exc, "error_code", type(exc).__name__
        )[:80]
        identity.save(
            update_fields=(
                "sync_status",
                "last_attempted_at",
                "last_error_code",
                "updated_at",
            )
        )
        raise


register_job_handler(CUSTOMER_UPSERT_JOB, upsert_customer_job)


__all__ = ["CUSTOMER_UPSERT_JOB", "upsert_customer_job"]
