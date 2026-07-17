from django.test import TestCase, override_settings

from dotykacka.services.registration import run_registration_followups
from integrations.models import IntegrationJob

from .base import (
    configure_brevo,
    configure_dotykacka,
    configure_google_wallet,
    create_klient,
)


class RegistrationWorkflowCompatibilityTests(TestCase):
    @override_settings(
        APPLE_WALLET_PASS_TYPE_IDENTIFIER="pass.example.test",
        APPLE_WALLET_TEAM_IDENTIFIER="TEAM123",
    )
    def test_legacy_entrypoint_creates_durable_provider_jobs(self):
        klient = create_klient("MB-12")
        configure_dotykacka(klient.tenant)
        configure_brevo(klient.tenant)
        configure_google_wallet(klient.tenant)

        jobs = run_registration_followups(klient.pk)

        self.assertEqual(len(jobs), 5)
        self.assertEqual(
            set(IntegrationJob.objects.values_list("kind", flat=True)),
            {
                "wallet.apple.issue",
                "wallet.google.issue",
                "pos.dotykacka.customer_upsert",
                "communications.brevo.contact_upsert",
                "communications.email.pass",
            },
        )

    def test_retrying_entrypoint_reuses_idempotency_keys(self):
        klient = create_klient("MB-12")
        configure_dotykacka(klient.tenant)
        run_registration_followups(klient.pk)
        first_count = IntegrationJob.objects.count()
        run_registration_followups(klient.pk)
        self.assertEqual(IntegrationJob.objects.count(), first_count)
