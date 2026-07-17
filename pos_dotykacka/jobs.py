"""Durable Dotykačka customer-upsert handler."""

from customers.models import Customer
from integrations.registry import register_job_handler

from .services import adapter_for_tenant


CUSTOMER_UPSERT_JOB = "pos.dotykacka.customer_upsert"


def upsert_customer_job(job):
    customer = Customer.objects.get(
        pk=job.payload["customer_id"], tenant=job.tenant
    )
    return adapter_for_tenant(job.tenant).upsert_customer(customer)


register_job_handler(CUSTOMER_UPSERT_JOB, upsert_customer_job)


__all__ = ["CUSTOMER_UPSERT_JOB", "upsert_customer_job"]
