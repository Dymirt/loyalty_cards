from unittest.mock import patch

from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from dotykacka.models import Klient

from .base import REGISTRATION_DATA, create_klient


class RegistrationViewTests(TestCase):
    def test_get_renders_named_consent_field(self):
        response = self.client.get(reverse("dotykacka:register"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="marketing_consent"')
        self.assertContains(response, 'name="first_name"')

    @patch("enrollment.views.start_registration_followups")
    def test_valid_registration_persists_customer_and_starts_workflow(self, start_workflow):
        response = self.client.post(reverse("dotykacka:register"), REGISTRATION_DATA)
        self.assertRedirects(response, reverse("index"))
        klient = Klient.objects.get(klient_id="MB-12")
        self.assertEqual(klient.email, "jan@example.test")
        self.assertEqual(klient.phone, "501234567")
        start_workflow.assert_called_once_with(klient.pk)

    @patch("enrollment.views.start_registration_followups")
    def test_invalid_registration_has_no_side_effects(self, start_workflow):
        response = self.client.post(
            reverse("dotykacka:register"),
            {**REGISTRATION_DATA, "barcode": "MB-INVALID"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Klient.objects.count(), 0)
        start_workflow.assert_not_called()

    def test_database_constraint_prevents_duplicate_registration_race(self):
        create_klient("MB-12")
        with self.assertRaises(IntegrityError), transaction.atomic():
            create_klient("MB-12", email="other@example.test")

    @patch("enrollment.views.start_registration_followups")
    @patch("customers.services.Customer.objects.create", side_effect=IntegrityError)
    def test_integrity_error_is_returned_as_duplicate_conflict(self, create, start_workflow):
        response = self.client.post(reverse("dotykacka:register"), REGISTRATION_DATA)
        self.assertEqual(response.status_code, 409)
        self.assertContains(response, "Ta karta już istnieje", status_code=409)
        start_workflow.assert_not_called()
