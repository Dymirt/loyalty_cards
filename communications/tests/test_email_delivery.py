from unittest.mock import patch

from django.test import TestCase, override_settings

from communications.jobs import send_pass_email_job
from communications.models import CommunicationDelivery
from dotykacka.tests.base import configure_google_wallet, create_physical_card, create_tenant
from enrollment.services import register_customer_with_card
from integrations.contracts import IntegrationError

from enrollment.tests.test_enrollment_services import cleaned_registration


@override_settings(
    APPLE_WALLET_PASS_TYPE_IDENTIFIER="",
    APPLE_WALLET_TEAM_IDENTIFIER="",
)
class EmailDeliverySafetyTests(TestCase):
    def setUp(self):
        self.tenant = create_tenant(name="Mail Café", slug="mail-cafe", card_prefix="MC")
        self.card = create_physical_card(self.tenant, number=6)
        configure_google_wallet(self.tenant)
        with self.captureOnCommitCallbacks(execute=True):
            self.enrollment = register_customer_with_card(
                tenant=self.tenant,
                cleaned_data=cleaned_registration(self.card.code),
            ).enrollment
        self.enrollment.customer.google_jwt_url = "https://wallet.example.test/save"
        self.enrollment.customer.save(update_fields=("google_jwt_url",))
        self.job = self.enrollment.followups.get(
            kind="communications.email.pass"
        ).integration_job

    @patch("communications.jobs.send_pass_email", return_value=1)
    def test_completed_delivery_is_not_automatically_sent_twice(self, send_email):
        first = send_pass_email_job(self.job)
        second = send_pass_email_job(self.job)

        self.assertEqual(first.pk, second.pk)
        self.assertEqual(first.status, CommunicationDelivery.Status.SENT)
        send_email.assert_called_once()

    @patch("communications.jobs.send_pass_email", side_effect=RuntimeError("smtp lost"))
    def test_unknown_outcome_blocks_automatic_replay(self, send_email):
        with self.assertRaises(IntegrationError):
            send_pass_email_job(self.job)
        delivery = CommunicationDelivery.objects.get(integration_job=self.job)
        self.assertEqual(delivery.status, CommunicationDelivery.Status.OUTCOME_UNKNOWN)

        with self.assertRaises(IntegrationError):
            send_pass_email_job(self.job)
        send_email.assert_called_once()
