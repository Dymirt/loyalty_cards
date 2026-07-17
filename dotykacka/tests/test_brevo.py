from unittest.mock import Mock, patch

from django.core.exceptions import ImproperlyConfigured
from django.test import TestCase, override_settings
from sib_api_v3_sdk.rest import ApiException

from dotykacka import brevo

from .base import create_klient


class BrevoServiceTests(TestCase):
    @override_settings(BREVO_API_KEY="")
    def test_missing_configuration_is_rejected_before_api_use(self):
        with self.assertRaises(ImproperlyConfigured):
            brevo._contacts_api()

    @patch("dotykacka.brevo._contacts_api")
    def test_customer_without_required_contact_data_is_skipped(self, contacts_api):
        klient = create_klient("MB-12", phone=None)
        self.assertFalse(brevo.send_contact_to_brevo(klient))
        contacts_api.assert_not_called()

    @override_settings(BREVO_LIST_ID=25, DEFAULT_PHONE_COUNTRY_CODE="+48")
    @patch("dotykacka.brevo._contacts_api")
    def test_contact_payload_normalizes_phone(self, contacts_api):
        api = Mock()
        contacts_api.return_value = api
        klient = create_klient("MB-12", phone="501234567")

        self.assertTrue(brevo.send_contact_to_brevo(klient))

        contact = api.create_contact.call_args.args[0]
        self.assertEqual(contact.email, "customer@example.test")
        self.assertEqual(contact.attributes["SMS"], "+48501234567")
        self.assertEqual(contact.list_ids, [25])

    @override_settings(BREVO_LIST_ID=25)
    @patch("dotykacka.brevo.add_contact_to_list")
    @patch("dotykacka.brevo._contacts_api")
    def test_duplicate_contact_is_added_to_configured_list(
        self, contacts_api, add_contact_to_list
    ):
        api = Mock()
        api.create_contact.side_effect = ApiException(
            status=400,
            reason="duplicate_parameter",
        )
        contacts_api.return_value = api
        klient = create_klient("MB-12")

        self.assertTrue(brevo.send_contact_to_brevo(klient))
        add_contact_to_list.assert_called_once_with(
            "customer@example.test", 25, api
        )
