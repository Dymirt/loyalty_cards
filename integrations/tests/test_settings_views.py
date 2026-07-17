from django.test import TestCase, override_settings
from django.urls import reverse

from integrations.models import IntegrationConnection
from pos_dotykacka.models import DotykackaConnectState

from dotykacka.models import AuditEvent
from dotykacka.tests.base import (
    configure_integration,
    create_tenant,
    create_tenant_owner,
)


class IntegrationSettingsViewTests(TestCase):
    def setUp(self):
        self.tenant = create_tenant()
        self.owner = create_tenant_owner(self.tenant)

    def test_non_owner_cannot_open_or_connect_integrations(self):
        outsider_tenant = create_tenant(slug="outsider", card_prefix="OT")
        outsider = create_tenant_owner(outsider_tenant, username="outsider")
        self.client.force_login(outsider)
        self.assertEqual(
            self.client.get(reverse("integrations:settings", args=[self.tenant.slug])).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(reverse("pos_dotykacka:connect", args=[self.tenant.slug])).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(
                reverse("pos_dotykacka:disconnect", args=[self.tenant.slug])
            ).status_code,
            403,
        )

    @override_settings(
        ALLOWED_HOSTS=["club.example.test"],
        DOTYKACKA_CONNECTOR_CLIENT_ID="client-id",
        DOTYKACKA_CONNECTOR_CLIENT_SECRET="connector-secret",
    )
    def test_tenant_owner_starts_connector_without_exposing_secret(self):
        self.client.force_login(self.owner)
        settings_response = self.client.get(
            reverse("integrations:settings", args=[self.tenant.slug]),
            HTTP_HOST="club.example.test",
        )
        self.assertContains(settings_response, "Autoryzacja Dotykačka")
        self.assertContains(settings_response, "Połącz z Dotykačka")
        self.assertContains(
            settings_response,
            reverse("pos_dotykacka:connect", args=[self.tenant.slug]),
        )
        response = self.client.post(
            reverse("pos_dotykacka:connect", args=[self.tenant.slug]),
            HTTP_HOST="club.example.test",
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "https://admin.dotykacka.cz/client/connect/v2")
        self.assertContains(response, 'name="signature"')
        self.assertNotContains(response, "connector-secret")
        self.assertEqual(DotykackaConnectState.objects.filter(tenant=self.tenant).count(), 1)

    @override_settings(
        DOTYKACKA_CONNECTOR_CLIENT_ID="",
        DOTYKACKA_CONNECTOR_CLIENT_SECRET="",
    )
    def test_missing_platform_connector_configuration_returns_to_tenant_page(self):
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse("pos_dotykacka:connect", args=[self.tenant.slug]),
        )

        self.assertRedirects(
            response,
            reverse("integrations:settings", args=[self.tenant.slug]),
        )
        self.assertFalse(DotykackaConnectState.objects.exists())

    def test_owner_cannot_run_platform_dotykacka_test(self):
        configure_integration(
            self.tenant,
            IntegrationConnection.Provider.DOTYKACKA,
            configuration={"cloud_id": 123, "discount_group_id": 456},
            secrets={"refresh_token": "connector-owned-refresh"},
        )
        self.client.force_login(self.owner)

        self.assertEqual(
            self.client.post(
                reverse(
                    "integrations:test",
                    args=[self.tenant.slug, IntegrationConnection.Provider.DOTYKACKA],
                )
            ).status_code,
            403,
        )

    def test_dotykacka_refresh_token_is_not_rendered_or_accepted_from_settings(self):
        connection = configure_integration(
            self.tenant,
            IntegrationConnection.Provider.DOTYKACKA,
            configuration={"cloud_id": 123, "discount_group_id": 456},
            secrets={"refresh_token": "connector-owned-refresh"},
        )
        self.client.force_login(self.owner)

        response = self.client.get(
            reverse("integrations:settings", args=[self.tenant.slug])
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Refresh token (opcjonalnie ręcznie)")
        self.assertNotContains(response, 'name="dotykacka-refresh_token"')
        self.assertContains(response, "Autoryzacja Dotykačka")
        self.assertContains(response, "Cloud ID: <strong>123</strong>", html=True)
        self.assertContains(response, "Odnów dostęp")
        self.assertContains(response, "Rozłącz Dotykačka")
        self.assertNotContains(response, 'name="dotykacka-cloud_id"')
        self.assertNotContains(response, "Ostatni test:")
        self.assertNotContains(response, "Token dostępu")
        self.assertContains(
            response,
            reverse("pos_dotykacka:connect", args=[self.tenant.slug]),
        )

        response = self.client.post(
            reverse("integrations:settings", args=[self.tenant.slug]),
            {
                "provider": "dotykacka",
                "dotykacka-enabled": "on",
                "dotykacka-cloud_id": "123",
                "dotykacka-discount_group_id": "456",
                "dotykacka-refresh_token": "attacker-supplied-token",
            },
        )
        self.assertEqual(response.status_code, 302)
        connection.refresh_from_db()
        self.assertEqual(connection.configuration["cloud_id"], 123)
        self.assertEqual(
            connection.get_secret("refresh_token"),
            "connector-owned-refresh",
        )

    def test_dotykacka_settings_require_tenant_connector_authorization(self):
        connection = IntegrationConnection.objects.create(
            tenant=self.tenant,
            provider=IntegrationConnection.Provider.DOTYKACKA,
        )
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse("integrations:settings", args=[self.tenant.slug]),
            {
                "provider": "dotykacka",
                "dotykacka-enabled": "on",
                "dotykacka-cloud_id": "350830718",
                "dotykacka-discount_group_id": "456",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "Najpierw połącz konto firmy przez Dotykačka Connector.",
        )
        connection.refresh_from_db()
        self.assertFalse(connection.enabled)
        self.assertEqual(connection.configuration, {})
        self.assertEqual(connection.get_credentials(), {})

    def test_owner_disconnects_before_cloud_can_change(self):
        connection = configure_integration(
            self.tenant,
            IntegrationConnection.Provider.DOTYKACKA,
            configuration={"cloud_id": "350830718", "discount_group_id": 456},
            secrets={
                "authorization_token": "User preserved-legacy-token",
                "refresh_token": "tenant-refresh-token",
            },
        )
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse("pos_dotykacka:disconnect", args=[self.tenant.slug]),
        )

        self.assertRedirects(
            response,
            reverse("integrations:settings", args=[self.tenant.slug]),
        )
        connection.refresh_from_db()
        self.assertFalse(connection.enabled)
        self.assertNotIn("cloud_id", connection.configuration)
        self.assertFalse(connection.has_secret("refresh_token"))
        self.assertEqual(
            connection.get_secret("authorization_token"),
            "User preserved-legacy-token",
        )
        event = AuditEvent.objects.get(action="integration.disconnected")
        self.assertEqual(event.tenant, self.tenant)
        self.assertEqual(event.actor, self.owner)
        self.assertEqual(event.metadata["cloud_id"], "350830718")

    def test_google_wallet_identifiers_are_not_tenant_editable(self):
        connection = configure_integration(
            self.tenant,
            IntegrationConnection.Provider.GOOGLE_WALLET,
            configuration={"issuer_id": "legacy-issuer", "class_suffix": "LEGACY"},
        )
        self.client.force_login(self.owner)

        response = self.client.get(
            reverse("integrations:settings", args=[self.tenant.slug])
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "ID wydawcy")
        self.assertNotContains(response, "Sufiks klasy")
        self.assertNotContains(
            response,
            reverse(
                "integrations:test",
                args=[self.tenant.slug, IntegrationConnection.Provider.GOOGLE_WALLET],
            ),
        )

        response = self.client.post(
            reverse("integrations:settings", args=[self.tenant.slug]),
            {
                "provider": "google_wallet",
                "google_wallet-enabled": "on",
                "google_wallet-issuer_id": "attacker-issuer",
                "google_wallet-class_suffix": "ATTACKER",
            },
        )
        self.assertEqual(response.status_code, 302)
        connection.refresh_from_db()
        self.assertTrue(connection.enabled)
        self.assertEqual(
            connection.configuration,
            {"issuer_id": "legacy-issuer", "class_suffix": "LEGACY"},
        )

    def test_owner_cannot_invoke_platform_google_test_through_tenant_route(self):
        configure_integration(
            self.tenant,
            IntegrationConnection.Provider.GOOGLE_WALLET,
        )
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse(
                "integrations:test",
                args=[self.tenant.slug, IntegrationConnection.Provider.GOOGLE_WALLET],
            )
        )

        self.assertEqual(response.status_code, 403)
