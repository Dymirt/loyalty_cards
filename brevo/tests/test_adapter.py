from unittest.mock import Mock

import requests
from django.test import TestCase, override_settings

from brevo.services import BrevoAdapter, ConsentRequiredError
from customers.models import CustomerExternalIdentity
from customers.services import record_marketing_consent
from integrations.contracts import RetryableIntegrationError

from dotykacka.tests.base import configure_brevo, create_klient, create_tenant


class Response:
    def __init__(self, status=200, payload=None, headers=None):
        self.status_code = status
        self._payload = payload if payload is not None else {}
        self.headers = headers or {}
        self.content = b"{}" if payload is not None else b""

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


@override_settings(INTEGRATION_HTTP_RETRIES=0, BREVO_HTTP_TIMEOUT=3)
class BrevoAdapterTests(TestCase):
    def _customer(self, tenant, code):
        customer = create_klient(code, tenant=tenant)
        record_marketing_consent(customer=customer, consent_text="Marketing v1")
        return customer

    def test_upsert_uses_tenant_key_list_ext_id_and_never_force_merge(self):
        first_tenant = create_tenant(slug="first", card_prefix="FA")
        second_tenant = create_tenant(slug="second", card_prefix="FB")
        first_connection = configure_brevo(first_tenant)
        second_connection = configure_brevo(second_tenant)
        second_connection.configuration["list_id"] = 99
        second_connection.set_credentials({"api_key": "second-key"})
        second_connection.save()
        first_customer = self._customer(first_tenant, "FA-1")
        second_customer = self._customer(second_tenant, "FB-1")
        first_http = Mock()
        first_http.post.return_value = Response(201, {"id": 11})
        second_http = Mock()
        second_http.post.return_value = Response(201, {"id": 22})

        BrevoAdapter(first_connection, session=first_http).upsert_contact(first_customer)
        BrevoAdapter(second_connection, session=second_http).upsert_contact(second_customer)

        first_payload = first_http.post.call_args.kwargs["json"]
        second_payload = second_http.post.call_args.kwargs["json"]
        self.assertEqual(first_payload["listIds"], [25])
        self.assertEqual(second_payload["listIds"], [99])
        self.assertNotIn("forceMerge", first_payload)
        self.assertNotIn("emailBlacklisted", first_payload)
        self.assertEqual(first_payload["attributes"]["SMS"], "+48501234567")
        self.assertNotEqual(first_payload["ext_id"], second_payload["ext_id"])
        self.assertEqual(first_http.post.call_args.kwargs["headers"]["api-key"], "brevo-test-key")
        self.assertEqual(second_http.post.call_args.kwargs["headers"]["api-key"], "second-key")
        self.assertEqual(CustomerExternalIdentity.objects.count(), 2)

    def test_no_consent_blocks_network_and_records_disabled_identity(self):
        tenant = create_tenant()
        connection = configure_brevo(tenant)
        customer = create_klient("SC-1", tenant=tenant)
        http = Mock()
        with self.assertRaises(ConsentRequiredError):
            BrevoAdapter(connection, session=http).upsert_contact(customer)
        http.post.assert_not_called()
        identity = CustomerExternalIdentity.objects.get(customer=customer)
        self.assertEqual(identity.sync_status, CustomerExternalIdentity.SyncStatus.DISABLED)

    def test_duplicate_updates_list_without_force_merge_or_blacklist_overwrite(self):
        tenant = create_tenant()
        connection = configure_brevo(tenant)
        customer = self._customer(tenant, "SC-1")
        http = Mock()
        http.post.return_value = Response(400, {"code": "duplicate_parameter"})
        http.get.return_value = Response(200, {"id": 77, "listIds": [7]})
        http.put.return_value = Response(204)

        BrevoAdapter(connection, session=http).upsert_contact(customer)

        update_payload = http.put.call_args.kwargs["json"]
        self.assertEqual(update_payload["listIds"], [7, 25])
        self.assertNotIn("forceMerge", update_payload)
        self.assertNotIn("emailBlacklisted", update_payload)

    def test_429_header_and_timeout_become_resumable_errors(self):
        tenant = create_tenant()
        connection = configure_brevo(tenant)
        customer = self._customer(tenant, "SC-1")
        limited_http = Mock()
        limited_http.post.return_value = Response(
            429, {"code": "rate_limit"}, {"x-sib-ratelimit-reset": "23"}
        )
        with self.assertRaises(RetryableIntegrationError) as limited:
            BrevoAdapter(connection, session=limited_http).upsert_contact(customer)
        self.assertEqual(limited.exception.retry_after, 23)
        timeout_http = Mock()
        timeout_http.post.side_effect = requests.Timeout("network details")
        with self.assertRaises(RetryableIntegrationError) as timeout:
            BrevoAdapter(connection, session=timeout_http).upsert_contact(customer)
        self.assertEqual(timeout.exception.error_code, "brevo_network")
