from unittest.mock import Mock

import requests
from django.test import SimpleTestCase, override_settings

from integrations.contracts import RetryableIntegrationError
from wallet_google.services import GoogleWalletRestClient


class Response:
    def __init__(self, status=200, payload=None, headers=None):
        self.status_code = status
        self._payload = payload or {}
        self.headers = headers or {}
        self.content = b"{}"

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


@override_settings(INTEGRATION_HTTP_RETRIES=0, GOOGLE_WALLET_HTTP_TIMEOUT=3)
class GoogleWalletRestAdapterTests(SimpleTestCase):
    def _client(self, session):
        client = GoogleWalletRestClient(session=session)
        client._token = "access-token"
        return client

    def test_class_and_object_are_upserted_with_stable_ids(self):
        session = Mock()
        session.get.side_effect = [Response(404), Response(404)]
        session.post.side_effect = [Response(200), Response(200)]
        class_payload = {"id": "issuer.class", "issuerName": "Cafe"}
        object_payload = {"id": "issuer.object", "classId": "issuer.class"}

        result = self._client(session).upsert_loyalty(
            class_payload=class_payload,
            object_payload=object_payload,
        )

        self.assertEqual(result.remote_id, "issuer.object")
        self.assertEqual(session.post.call_args_list[0].args[0].rsplit("/", 1)[-1], "loyaltyClass")
        self.assertEqual(session.post.call_args_list[1].args[0].rsplit("/", 1)[-1], "loyaltyObject")
        self.assertEqual(session.post.call_args_list[1].kwargs["json"]["id"], "issuer.object")

    def test_429_is_resumable_and_uses_retry_after(self):
        session = Mock()
        session.get.return_value = Response(429, headers={"Retry-After": "31"})
        with self.assertRaises(RetryableIntegrationError) as error:
            self._client(session).upsert_loyalty(
                class_payload={"id": "issuer.class"},
                object_payload={"id": "issuer.object"},
            )
        self.assertEqual(error.exception.retry_after, 31)

    def test_issuer_check_is_read_only(self):
        session = Mock()
        session.get.return_value = Response(200, {"resources": []})

        result = self._client(session).test_issuer("3388000000022973962")

        self.assertEqual(result.metadata["issuer_id"], "3388000000022973962")
        session.get.assert_called_once()
        self.assertEqual(
            session.get.call_args.kwargs["params"],
            {"issuerId": "3388000000022973962", "maxResults": 1},
        )
        session.post.assert_not_called()
