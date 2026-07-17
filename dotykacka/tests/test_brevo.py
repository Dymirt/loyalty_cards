from django.core.exceptions import ImproperlyConfigured
from django.test import TestCase

from customers.services import record_marketing_consent
from dotykacka import brevo

from .base import configure_brevo, create_klient, default_tenant


class BrevoCompatibilityTests(TestCase):
    def test_missing_configuration_uses_historical_exception_type(self):
        with self.assertRaises(ImproperlyConfigured):
            brevo._connection_for(default_tenant())

    def test_customer_without_required_contact_data_is_skipped(self):
        klient = create_klient("MB-12", phone=None)
        self.assertFalse(brevo.send_contact_to_brevo(klient))

    def test_legacy_connection_lookup_returns_tenant_connection(self):
        connection = configure_brevo()
        self.assertEqual(brevo._connection_for(default_tenant()), connection)

    def test_consent_evidence_is_available_to_the_final_adapter(self):
        klient = create_klient("MB-12")
        self.assertFalse(klient.consent_records.exists())
        record_marketing_consent(customer=klient, consent_text="Marketing")
        self.assertTrue(klient.consent_records.filter(granted=True).exists())
