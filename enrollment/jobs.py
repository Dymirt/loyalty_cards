"""Create idempotent provider follow-ups after local enrollment commits."""

from django.conf import settings
from django.db import transaction

from integrations.models import IntegrationConnection
from integrations.services import enqueue_job

from .models import Enrollment, EnrollmentEvent, EnrollmentFollowUp


EMAIL_JOB_KIND = "communications.email.pass"


def _followup_specs(customer):
    connections = {
        connection.provider: connection
        for connection in IntegrationConnection.objects.filter(
            tenant=customer.tenant,
            enabled=True,
        )
    }
    specs = []
    apple_enabled = bool(
        settings.APPLE_WALLET_PASS_TYPE_IDENTIFIER
        and settings.APPLE_WALLET_TEAM_IDENTIFIER
    )
    if apple_enabled:
        specs.append(("wallet.apple.issue", None))
    google = connections.get(IntegrationConnection.Provider.GOOGLE_WALLET)
    if google:
        specs.append(("wallet.google.issue", google))
    dotykacka = connections.get(IntegrationConnection.Provider.DOTYKACKA)
    if dotykacka:
        specs.append(("pos.dotykacka.customer_upsert", dotykacka))
    brevo = connections.get(IntegrationConnection.Provider.BREVO)
    if brevo:
        specs.append(("communications.brevo.contact_upsert", brevo))
    if customer.email and (apple_enabled or google):
        specs.append((EMAIL_JOB_KIND, None))
    return specs


@transaction.atomic
def enqueue_enrollment_followups(enrollment_id):
    enrollment = (
        Enrollment.objects.select_for_update()
        .select_related("customer", "tenant")
        .get(pk=enrollment_id)
    )
    link = enrollment.access_links.order_by("-created_at", "-pk").first()
    jobs = []
    for kind, connection in _followup_specs(enrollment.customer):
        payload = {"customer_id": enrollment.customer_id}
        if kind == EMAIL_JOB_KIND and link:
            payload["enrollment_link_id"] = link.pk
        job = enqueue_job(
            tenant=enrollment.tenant,
            connection=connection,
            kind=kind,
            idempotency_key=f"enrollment:{enrollment.customer_id}:{kind}:v1",
            payload=payload,
        )
        followup, _ = EnrollmentFollowUp.objects.get_or_create(
            enrollment=enrollment,
            kind=kind,
            generation=1,
            defaults={
                "integration_job": job,
                "operation": EnrollmentFollowUp.Operation.INITIAL,
            },
        )
        EnrollmentEvent.objects.get_or_create(
            enrollment=enrollment,
            idempotency_key=f"followup-enqueued:{job.pk}",
            defaults={
                "kind": EnrollmentEvent.Kind.FOLLOWUPS_ENQUEUED,
                "integration_job": job,
                "metadata": {
                    "followup_id": followup.pk,
                    "kind": kind,
                    "generation": 1,
                },
            },
        )
        jobs.append(job)
    return jobs


def enqueue_registration_followups(customer_id):
    from customers.models import Customer

    customer = Customer.objects.select_related("tenant").get(pk=customer_id)
    try:
        enrollment = customer.enrollment
    except Enrollment.DoesNotExist:
        enrollment = None
    if enrollment is not None:
        return enqueue_enrollment_followups(enrollment.pk)
    jobs = []
    for kind, connection in _followup_specs(customer):
        jobs.append(
            enqueue_job(
                tenant=customer.tenant,
                connection=connection,
                kind=kind,
                idempotency_key=f"enrollment:{customer.pk}:{kind}:v1",
                payload={"customer_id": customer.pk},
            )
        )
    return jobs


__all__ = [
    "EMAIL_JOB_KIND",
    "enqueue_enrollment_followups",
    "enqueue_registration_followups",
]
