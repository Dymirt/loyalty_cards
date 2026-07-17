import hashlib
import hmac
from datetime import timedelta
from unittest.mock import Mock, patch

import requests
from django.test import TestCase, override_settings
from django.utils import timezone

from customers.models import CustomerExternalIdentity
from integrations.contracts import (
    IntegrationAuthenticationError,
    IntegrationConfigurationError,
    RetryableIntegrationError,
)
from pos_dotykacka.models import DotykackaAccessToken, DotykackaConnectState
from pos_dotykacka.services import (
    DotykackaAdapter,
    begin_connection,
    complete_connection,
    connector_payload,
    connector_system_check,
    disconnect_connection,
    get_connection,
    tenant_connections_system_check,
)

from dotykacka.tests.base import (
    configure_dotykacka,
    create_klient,
    create_superuser,
    create_tenant,
    create_tenant_owner,
)


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


CONNECTOR_SETTINGS = {
    "DOTYKACKA_CONNECTOR_CLIENT_ID": "client-123",
    "DOTYKACKA_CONNECTOR_CLIENT_SECRET": "platform-secret",
    "DOTYKACKA_CONNECTOR_URL": "https://admin.dotykacka.cz/client/connect/v2",
}


class ConnectorTests(TestCase):
    @override_settings(**CONNECTOR_SETTINGS)
    def test_payload_uses_official_hmac_timestamp_contract(self):
        payload = connector_payload(
            redirect_uri="https://club.test/callback",
            timestamp=1704123456,
            state="csrf-state",
        )
        expected = hmac.new(
            b"platform-secret", b"1704123456", hashlib.sha256
        ).hexdigest()
        self.assertEqual(payload["signature"], expected)
        self.assertEqual(payload["scope"], "*")
        self.assertNotIn("client_secret", payload)

    @override_settings(**CONNECTOR_SETTINGS, DOTYKACKA_CLOUD_ID=987654)
    def test_platform_signature_never_uses_tenant_refresh_token_or_cloud_id(self):
        payload = connector_payload(
            redirect_uri="https://club.test/callback",
            timestamp=1704123456,
            state="csrf-state",
        )
        platform_signature = hmac.new(
            b"platform-secret", b"1704123456", hashlib.sha256
        ).hexdigest()
        refresh_token_signature = hmac.new(
            b"tenant-refresh-token", b"1704123456", hashlib.sha256
        ).hexdigest()

        self.assertEqual(payload["client_id"], "client-123")
        self.assertEqual(payload["signature"], platform_signature)
        self.assertNotEqual(payload["signature"], refresh_token_signature)
        self.assertNotIn("cloud_id", payload)

    @override_settings(
        DOTYKACKA_CONNECTOR_CLIENT_ID="",
        DOTYKACKA_CONNECTOR_CLIENT_SECRET="",
        DOTYKACKA_CLOUD_ID=987654,
    )
    def test_tenant_credentials_cannot_satisfy_platform_connector_configuration(self):
        result = connector_system_check()

        self.assertFalse(result.ok)
        self.assertEqual(
            result.details,
            (
                "Brak zmiennej: DOTYKACKA_CONNECTOR_CLIENT_ID",
                "Brak zmiennej: DOTYKACKA_CONNECTOR_CLIENT_SECRET",
            ),
        )
        with self.assertRaises(IntegrationConfigurationError) as error:
            connector_payload(redirect_uri="https://club.test/callback")
        self.assertEqual(
            error.exception.error_code,
            "dotykacka_connector_credentials_missing",
        )

    @override_settings(
        DOTYKACKA_CONNECTOR_CLIENT_ID="client-123",
        DOTYKACKA_CONNECTOR_CLIENT_SECRET="",
    )
    def test_diagnostic_names_only_the_missing_platform_secret(self):
        result = connector_system_check()

        self.assertFalse(result.ok)
        self.assertEqual(
            result.details,
            ("Brak zmiennej: DOTYKACKA_CONNECTOR_CLIENT_SECRET",),
        )

    @override_settings(**CONNECTOR_SETTINGS)
    def test_diagnostic_confirms_local_signing_without_exposing_secret(self):
        result = connector_system_check()

        self.assertTrue(result.ok)
        self.assertIn("HMAC-SHA256", result.summary)
        self.assertNotIn("platform-secret", " ".join(result.details))

    @override_settings(**CONNECTOR_SETTINGS)
    def test_state_is_tenant_user_session_bound_and_single_use(self):
        tenant = create_tenant()
        user = create_tenant_owner(tenant)
        _, payload = begin_connection(
            tenant=tenant,
            user=user,
            session_key="browser-session",
            redirect_uri="https://club.test/callback",
        )
        pending = DotykackaConnectState.objects.get()
        self.assertNotEqual(pending.state_digest, payload["state"])
        with self.assertRaises(IntegrationAuthenticationError):
            complete_connection(
                state=payload["state"],
                refresh_token="refresh",
                cloud_id="cloud-1",
                user=user,
                session_key="other-session",
            )
        connection = complete_connection(
            state=payload["state"],
            refresh_token="refresh",
            cloud_id="cloud-1",
            user=user,
            session_key="browser-session",
        )
        self.assertEqual(connection.get_secret("refresh_token"), "refresh")
        self.assertEqual(connection.configuration["cloud_id"], "cloud-1")
        with self.assertRaises(IntegrationAuthenticationError):
            complete_connection(
                state=payload["state"],
                refresh_token="refresh-2",
                cloud_id="cloud-2",
                user=user,
                session_key="browser-session",
            )

    @override_settings(**CONNECTOR_SETTINGS)
    def test_connected_cloud_cannot_change_before_disconnect(self):
        tenant = create_tenant()
        user = create_tenant_owner(tenant)
        _, first = begin_connection(
            tenant=tenant,
            user=user,
            session_key="browser-session",
            redirect_uri="https://club.test/callback",
        )
        connection = complete_connection(
            state=first["state"],
            refresh_token="first-refresh",
            cloud_id="cloud-1",
            user=user,
            session_key="browser-session",
        )
        _, second = begin_connection(
            tenant=tenant,
            user=user,
            session_key="browser-session",
            redirect_uri="https://club.test/callback",
        )

        with self.assertRaises(IntegrationAuthenticationError) as error:
            complete_connection(
                state=second["state"],
                refresh_token="second-refresh",
                cloud_id="cloud-2",
                user=user,
                session_key="browser-session",
            )

        self.assertEqual(error.exception.error_code, "cloud_change_requires_disconnect")
        connection.refresh_from_db()
        self.assertEqual(connection.configuration["cloud_id"], "cloud-1")
        self.assertEqual(connection.get_secret("refresh_token"), "first-refresh")

    @override_settings(**CONNECTOR_SETTINGS)
    def test_disconnect_invalidates_tokens_and_pending_connector_states(self):
        tenant = create_tenant()
        user = create_tenant_owner(tenant)
        connection = configure_dotykacka(tenant)
        cached = DotykackaAccessToken(
            tenant=tenant,
            connection=connection,
            cloud_id=str(connection.configuration["cloud_id"]),
            obtained_at=timezone.now(),
            expires_at=timezone.now() + timedelta(minutes=30),
        )
        cached.set_token("short-lived-access")
        cached.save()
        begin_connection(
            tenant=tenant,
            user=user,
            session_key="browser-session",
            redirect_uri="https://club.test/callback",
        )

        disconnected, previous_cloud_id = disconnect_connection(tenant=tenant)

        disconnected.refresh_from_db()
        cached.refresh_from_db()
        pending = DotykackaConnectState.objects.get(connection=connection)
        self.assertEqual(previous_cloud_id, "123")
        self.assertFalse(disconnected.enabled)
        self.assertFalse(disconnected.has_secret("refresh_token"))
        self.assertTrue(disconnected.has_secret("authorization_token"))
        self.assertNotIn("cloud_id", disconnected.configuration)
        self.assertIsNotNone(cached.invalidated_at)
        self.assertIsNotNone(pending.used_at)


@override_settings(INTEGRATION_HTTP_RETRIES=0, DOTYKACKA_HTTP_TIMEOUT=3)
class DotykackaAdapterTests(TestCase):
    def _cached_token(self, connection, value):
        cached = DotykackaAccessToken(
            tenant=connection.tenant,
            connection=connection,
            cloud_id=str(connection.configuration["cloud_id"]),
            obtained_at=timezone.now(),
            expires_at=timezone.now() + timedelta(minutes=30),
        )
        cached.set_token(value)
        cached.save()
        return cached

    def test_tenant_refresh_token_is_used_for_tenant_cloud_access(self):
        connection = configure_dotykacka(create_tenant())
        connection.set_credentials({"refresh_token": "tenant-refresh-token"})
        connection.save()
        http = Mock()
        http.post.return_value = Response(201, {"accessToken": "cloud-access"})

        token = DotykackaAdapter(connection, session=http).fetch_access_token()

        self.assertEqual(token, "cloud-access")
        self.assertEqual(
            http.post.call_args.kwargs["headers"]["Authorization"],
            "User tenant-refresh-token",
        )
        self.assertEqual(
            http.post.call_args.kwargs["json"],
            {"_cloudId": connection.configuration["cloud_id"]},
        )

    def test_tenant_refresh_token_authorization_scheme_is_normalized(self):
        connection = configure_dotykacka(create_tenant())
        connection.set_credentials({"refresh_token": "User tenant-refresh-token"})
        connection.save()
        http = Mock()
        http.post.return_value = Response(201, {"accessToken": "cloud-access"})

        DotykackaAdapter(connection, session=http).fetch_access_token()

        self.assertEqual(
            http.post.call_args.kwargs["headers"]["Authorization"],
            "User tenant-refresh-token",
        )

    def test_enabled_tenant_requires_its_own_refresh_token(self):
        connection = configure_dotykacka(create_tenant())
        connection.set_credentials({"authorization_token": "User legacy-only"})
        connection.save()

        with self.assertRaises(IntegrationConfigurationError):
            get_connection(connection.tenant)

    def test_system_check_reports_missing_tenant_refresh_token(self):
        connection = configure_dotykacka(create_tenant())
        connection.set_credentials({"authorization_token": "User legacy-only"})
        connection.save()

        result = tenant_connections_system_check()

        self.assertFalse(result.ok)
        self.assertEqual(
            result.details,
            (
                f"{connection.tenant.name}: błąd "
                "(dotykacka_refresh_token_missing)",
            ),
        )

    @patch("pos_dotykacka.services.test_connection")
    def test_system_check_reports_tenant_refresh_token_and_cloud(self, tester):
        connection = configure_dotykacka(create_tenant())
        connection.set_credentials({"refresh_token": "tenant-refresh-token"})
        connection.save()

        result = tenant_connections_system_check()

        self.assertTrue(result.ok)
        self.assertEqual(
            result.details,
            (
                f"{connection.tenant.name}: OK · Refresh Token firmy "
                f"(zaszyfrowany) · "
                f"Cloud ID {connection.configuration['cloud_id']}",
            ),
        )
        tester.assert_called_once_with(connection)

    def test_new_access_token_is_encrypted_and_tenant_scoped(self):
        first = configure_dotykacka(create_tenant(slug="first", card_prefix="FA"))
        second = configure_dotykacka(create_tenant(slug="second", card_prefix="FB"))
        first.set_credentials({"refresh_token": "first-refresh"})
        first.save()
        second.set_credentials({"refresh_token": "second-refresh"})
        second.save()
        first_http = Mock()
        first_http.post.return_value = Response(201, {"accessToken": "first-access"})
        second_http = Mock()
        second_http.post.return_value = Response(201, {"accessToken": "second-access"})

        self.assertEqual(DotykackaAdapter(first, session=first_http).fetch_access_token(), "first-access")
        self.assertEqual(DotykackaAdapter(second, session=second_http).fetch_access_token(), "second-access")

        tokens = list(DotykackaAccessToken.objects.order_by("tenant_id"))
        self.assertEqual({token.get_token() for token in tokens}, {"first-access", "second-access"})
        self.assertTrue(all("access" not in token.token_encrypted for token in tokens))
        self.assertEqual(
            first_http.post.call_args.kwargs["headers"]["Authorization"],
            "User first-refresh",
        )

    def test_one_401_invalidates_cache_refreshes_and_retries_once(self):
        connection = configure_dotykacka(create_tenant())
        self._cached_token(connection, "expired-access")
        http = Mock()
        http.get.side_effect = [
            Response(401),
            Response(200, {"data": [], "lastPage": 1}),
        ]
        http.post.return_value = Response(201, {"accessToken": "fresh-access"})

        self.assertEqual(DotykackaAdapter(connection, session=http).list_customers(), [])
        self.assertEqual(http.get.call_count, 2)
        self.assertEqual(
            http.get.call_args_list[1].kwargs["headers"]["Authorization"],
            "Bearer fresh-access",
        )
        self.assertEqual(
            DotykackaAccessToken.objects.filter(invalidated_at__isnull=False).count(),
            1,
        )

    def test_expired_access_token_is_refreshed_automatically(self):
        connection = configure_dotykacka(create_tenant())
        expired = self._cached_token(connection, "expired-access")
        expired.expires_at = timezone.now() - timedelta(seconds=1)
        expired.save(update_fields=("expires_at",))
        http = Mock()
        http.post.return_value = Response(201, {"accessToken": "fresh-access"})

        token = DotykackaAdapter(connection, session=http).valid_access_token()

        self.assertEqual(token, "fresh-access")
        self.assertEqual(http.post.call_count, 1)
        self.assertEqual(DotykackaAccessToken.objects.count(), 2)

    def test_429_and_timeout_are_retryable_without_secret_details(self):
        connection = configure_dotykacka(create_tenant())
        self._cached_token(connection, "cached")
        http = Mock()
        http.get.return_value = Response(
            429, {"error": "limited"}, {"Retry-After": "17"}
        )
        with self.assertRaises(RetryableIntegrationError) as limited:
            DotykackaAdapter(connection, session=http).list_customers()
        self.assertEqual(limited.exception.retry_after, 17)

        timeout_http = Mock()
        timeout_http.post.side_effect = requests.Timeout("network details")
        with self.assertRaises(RetryableIntegrationError) as timeout:
            DotykackaAdapter(connection, session=timeout_http).fetch_access_token()
        self.assertEqual(timeout.exception.error_code, "dotykacka_network")

    def test_duplicate_create_reconciles_stable_external_identity(self):
        tenant = create_tenant()
        connection = configure_dotykacka(tenant)
        customer = create_klient("SC-12", tenant=tenant)
        self._cached_token(connection, "cached")
        http = Mock()
        http.post.return_value = Response(409, {"error": "duplicate"})
        http.get.return_value = Response(
            200,
            {
                "data": [
                    {
                        "id": 77,
                        "barcode": "SC-12",
                        "_discountGroupId": 456,
                    }
                ],
                "lastPage": 1,
            },
        )
        result = DotykackaAdapter(connection, session=http).upsert_customer(customer)
        self.assertEqual(result.remote_id, "77")
        identity = CustomerExternalIdentity.objects.get(customer=customer)
        self.assertEqual(identity.remote_id, "77")
        self.assertEqual(identity.tenant, tenant)
