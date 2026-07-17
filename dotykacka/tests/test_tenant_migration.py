import importlib
import json

from cryptography.fernet import Fernet
from django.apps import apps as django_apps
from django.contrib.auth import get_user_model
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase, override_settings

from dotykacka.models import IntegrationConnection

from .base import create_tenant


class MartaBackfillMigrationTests(TransactionTestCase):
    migrate_from = [("dotykacka", "0008_alter_klient_klient_id_unique")]
    migrate_to = [("dotykacka", "0014_promote_dotykacka_refresh_tokens")]

    def setUp(self):
        super().setUp()
        self.encryption_key = Fernet.generate_key().decode("ascii")
        self.settings_override = override_settings(
            TENANT_SECRETS_ENCRYPTION_KEYS=[self.encryption_key],
            DOTYKACKA_AUTHORIZATION_TOKEN="User legacy-dotykacka-secret",
            DOTYKACKA_CLOUD_ID=321,
            DOTYKACKA_DISCOUNT_GROUP_ID=654,
            BREVO_API_KEY="legacy-brevo-secret",
            BREVO_LIST_ID=99,
            DEFAULT_PHONE_COUNTRY_CODE="+48",
            GOOGLE_WALLET_ISSUER_ID="legacy-issuer",
            GOOGLE_WALLET_CLASS_SUFFIX="MB",
        )
        self.settings_override.enable()

        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_from)
        old_apps = executor.loader.project_state(self.migrate_from).apps
        Klient = old_apps.get_model("dotykacka", "Klient")
        AccessToken = old_apps.get_model("dotykacka", "AccessToken")

        get_user_model().objects.create(
            username="admin",
            is_staff=True,
            is_superuser=True,
        )
        Klient.objects.create(klient_id="MB-1", email="one@example.test")
        Klient.objects.create(klient_id="MB-600", email="six@example.test")
        AccessToken.objects.create(token="cached-one")
        AccessToken.objects.create(token="cached-two")

        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_to)
        self.apps = executor.loader.project_state(self.migrate_to).apps

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
        self.settings_override.disable()
        super().tearDown()

    def test_existing_rows_are_assigned_without_replacement_or_secret_disclosure(self):
        Tenant = self.apps.get_model("dotykacka", "Tenant")
        TenantMembership = self.apps.get_model("dotykacka", "TenantMembership")
        IntegrationConnection = self.apps.get_model(
            "dotykacka", "IntegrationConnection"
        )
        AccessToken = self.apps.get_model("dotykacka", "AccessToken")
        Klient = self.apps.get_model("dotykacka", "Klient")
        PhysicalCard = self.apps.get_model("dotykacka", "PhysicalCard")
        CardDesign = self.apps.get_model("dotykacka", "CardDesign")
        TenantBrandRevision = self.apps.get_model("dotykacka", "TenantBrandRevision")
        WalletPass = self.apps.get_model("dotykacka", "WalletPass")

        tenant = Tenant.objects.get(slug="marta-banaszek-atelier-cafe")
        self.assertEqual(TenantMembership.objects.filter(tenant=tenant).count(), 1)
        self.assertEqual(Klient.objects.filter(tenant=tenant).count(), 2)
        self.assertEqual(
            AccessToken.objects.filter(connection__tenant=tenant).count(),
            2,
        )
        self.assertEqual(PhysicalCard.objects.filter(tenant=tenant).count(), 600)
        self.assertEqual(
            PhysicalCard.objects.filter(tenant=tenant, status="assigned").count(),
            2,
        )
        self.assertEqual(
            PhysicalCard.objects.get(code="MB-1").customer.klient_id,
            "MB-1",
        )
        self.assertEqual(
            PhysicalCard.objects.get(code="MB-600").customer.klient_id,
            "MB-600",
        )
        design = CardDesign.objects.get(tenant=tenant, version=1)
        self.assertEqual(design.background_source.name, "Marta Banaszek - Obraz II.jpg")
        self.assertEqual(design.layout_preset, "marta_legacy")
        self.assertEqual(TenantBrandRevision.objects.filter(tenant=tenant).count(), 1)
        self.assertEqual(WalletPass.objects.filter(tenant=tenant).count(), 2)
        self.assertEqual(
            WalletPass.objects.get(customer__klient_id="MB-1").google_object_id,
            "legacy-issuer.MB-1",
        )

        dotykacka = IntegrationConnection.objects.get(
            tenant=tenant,
            provider="dotykacka",
        )
        brevo = IntegrationConnection.objects.get(tenant=tenant, provider="brevo")
        self.assertEqual(dotykacka.configuration["cloud_id"], 321)
        self.assertEqual(dotykacka.configuration["discount_group_id"], 654)
        self.assertEqual(brevo.configuration["list_id"], 99)
        self.assertTrue(dotykacka.credentials_encrypted.startswith("fernet:v1:"))
        self.assertTrue(brevo.credentials_encrypted.startswith("fernet:v1:"))
        self.assertNotIn("legacy-dotykacka-secret", dotykacka.credentials_encrypted)
        self.assertNotIn("legacy-brevo-secret", brevo.credentials_encrypted)
        encrypted_payload = dotykacka.credentials_encrypted.removeprefix(
            "fernet:v1:"
        )
        credentials = json.loads(
            Fernet(self.encryption_key.encode("ascii"))
            .decrypt(encrypted_payload.encode("ascii"))
            .decode("utf-8")
        )
        self.assertEqual(
            credentials,
            {
                "authorization_token": "User legacy-dotykacka-secret",
                "refresh_token": "legacy-dotykacka-secret",
            },
        )


class RefreshTokenDataMigrationSafetyTests(TestCase):
    def test_existing_refresh_token_is_never_overwritten(self):
        tenant = create_tenant()
        connection = IntegrationConnection.objects.create(
            tenant=tenant,
            provider=IntegrationConnection.Provider.DOTYKACKA,
        )
        connection.set_credentials(
            {
                "authorization_token": "User legacy-authorization",
                "refresh_token": "existing-connector-refresh",
            }
        )
        connection.save()
        migration = importlib.import_module(
            "dotykacka.migrations.0014_promote_dotykacka_refresh_tokens"
        )

        migration.promote_legacy_authorization_to_refresh_token(
            django_apps,
            schema_editor=None,
        )

        connection.refresh_from_db()
        self.assertEqual(
            connection.get_credentials(),
            {
                "authorization_token": "User legacy-authorization",
                "refresh_token": "existing-connector-refresh",
            },
        )
