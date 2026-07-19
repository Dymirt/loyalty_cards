from unittest.mock import patch

from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse

from dotykacka.models import Klient
from enrollment.models import Enrollment
from integrations.models import IntegrationJob

from .base import REGISTRATION_DATA, create_klient


@override_settings(
    APPLE_WALLET_PASS_TYPE_IDENTIFIER="",
    APPLE_WALLET_TEAM_IDENTIFIER="",
)
class RegistrationViewTests(TestCase):
    def test_get_renders_named_consent_field(self):
        response = self.client.get(reverse("dotykacka:register"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="marketing_consent"')
        self.assertContains(response, 'name="first_name"')

    def test_valid_registration_persists_customer_and_starts_workflow(self):
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            response = self.client.post(reverse("dotykacka:register"), REGISTRATION_DATA)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/enrollment/status/", response.url)
        klient = Klient.objects.get(klient_id="MB-12")
        self.assertEqual(klient.email, "jan@example.test")
        self.assertEqual(klient.phone, "501234567")
        self.assertEqual(Enrollment.objects.filter(customer=klient).count(), 1)
        self.assertEqual(len(callbacks), 1)

    def test_invalid_registration_has_no_side_effects(self):
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            response = self.client.post(
                reverse("dotykacka:register"),
                {**REGISTRATION_DATA, "barcode": "MB-INVALID"},
            )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Klient.objects.count(), 0)
        self.assertEqual(Enrollment.objects.count(), 0)
        self.assertEqual(IntegrationJob.objects.count(), 0)
        self.assertEqual(callbacks, [])

    def test_database_constraint_prevents_duplicate_registration_race(self):
        create_klient("MB-12")
        with self.assertRaises(IntegrityError), transaction.atomic():
            create_klient("MB-12", email="other@example.test")

    @patch("enrollment.services.create_customer", side_effect=IntegrityError)
    def test_integrity_error_is_returned_as_duplicate_conflict(self, create):
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            response = self.client.post(reverse("dotykacka:register"), REGISTRATION_DATA)
        self.assertEqual(response.status_code, 409)
        self.assertContains(response, "Ta karta już istnieje", status_code=409)
        self.assertEqual(Enrollment.objects.count(), 0)
        self.assertEqual(callbacks, [])
