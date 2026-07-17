"""Durable Google Wallet issuance handler."""

from customers.models import Customer
from integrations.registry import register_job_handler

from .services import issuer


ISSUE_JOB = "wallet.google.issue"


def issue_google_job(job):
    customer = Customer.objects.get(
        pk=job.payload["customer_id"], tenant=job.tenant
    )
    return issuer.issue(customer)


register_job_handler(ISSUE_JOB, issue_google_job)


__all__ = ["ISSUE_JOB", "issue_google_job"]
