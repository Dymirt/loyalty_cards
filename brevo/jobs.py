"""Durable consent-gated Brevo contact-upsert handler."""

from customers.models import Customer
from integrations.registry import register_job_handler

from .services import adapter_for_tenant


CONTACT_UPSERT_JOB = "communications.brevo.contact_upsert"


def upsert_contact_job(job):
    customer = Customer.objects.get(
        pk=job.payload["customer_id"], tenant=job.tenant
    )
    return adapter_for_tenant(job.tenant).upsert_contact(customer)


register_job_handler(CONTACT_UPSERT_JOB, upsert_contact_job)


__all__ = ["CONTACT_UPSERT_JOB", "upsert_contact_job"]
