"""Create idempotent provider follow-ups after local enrollment commits."""

from django.conf import settings

from integrations.models import IntegrationConnection
from integrations.services import enqueue_job


def enqueue_registration_followups(customer_id):
    from customers.models import Customer

    customer = Customer.objects.select_related("tenant").get(pk=customer_id)
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
    if customer.email and apple_enabled:
        specs.append(("communications.email.pass", None))
    jobs = []
    for kind, connection in specs:
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


__all__ = ["enqueue_registration_followups"]
