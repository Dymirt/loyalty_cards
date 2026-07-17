from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from customers.models import ConsentRecord, Customer
from dotykacka.tests.base import REGISTRATION_DATA


class EnrollmentServiceTests(TestCase):
    @patch("enrollment.views.start_registration_followups")
    def test_registration_uses_domain_services_and_records_consent(self, followups):
        response = self.client.post(reverse("enrollment:register"), REGISTRATION_DATA)

        self.assertEqual(response.status_code, 302)
        customer = Customer.objects.get(klient_id="MB-12")
        self.assertEqual(customer.physical_card.code, "MB-12")
        consent = ConsentRecord.objects.get(customer=customer)
        self.assertTrue(consent.granted)
        self.assertEqual(consent.purpose, "marketing")
        followups.assert_called_once_with(customer.pk)
