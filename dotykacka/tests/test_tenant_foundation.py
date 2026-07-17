import json
from io import StringIO
from unittest.mock import patch

from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from dotykacka.models import (
    AuditEvent,
    IntegrationConnection,
    Klient,
    PhysicalCard,
    Tenant,
    TenantMembership,
)

from .base import (
    REGISTRATION_DATA,
    configure_dotykacka,
    create_physical_card,
    create_tenant,
    create_tenant_owner,
    create_superuser,
    default_tenant,
)


class MartaTenantBaselineTests(TestCase):
    def test_migration_creates_marta_brand_integrations_and_card_inventory(self):
        tenant = default_tenant()

        self.assertEqual(tenant.slug, "marta-banaszek-atelier-cafe")
        self.assertEqual(tenant.card_prefix, "MB")
        self.assertEqual(tenant.brand.public_name, "Atelier-Café Marta Banaszek")
        self.assertEqual(tenant.integrations.count(), 3)
        self.assertEqual(tenant.physical_cards.count(), 600)
        self.assertEqual(
            tenant.physical_cards.filter(status=PhysicalCard.Status.AVAILABLE).count(),
            600,
        )
        self.assertEqual(tenant.card_batches.get().name, "Legacy MB-1..600")

    def test_backfill_verifier_is_read_only_and_reports_aggregates(self):
        before = {
            "tenants": Tenant.objects.count(),
            "customers": Klient.objects.count(),
            "cards": PhysicalCard.objects.count(),
        }
        output = StringIO()

        call_command(
            "verify_marta_backfill",
            expect_memberships=0,
            expect_customers=0,
            expect_tokens=0,
            expect_cards=600,
            expect_assigned=0,
            expect_available=600,
            stdout=output,
        )

        result = json.loads(output.getvalue())
        self.assertEqual(result["status"], "ok")
        self.assertEqual(
            before,
            {
                "tenants": Tenant.objects.count(),
                "customers": Klient.objects.count(),
                "cards": PhysicalCard.objects.count(),
            },
        )


class TenantRegistrationIsolationTests(TestCase):
    @patch("dotykacka.views.start_registration_followups")
    @override_settings(APP_BASE_URL="https://club.example.test")
    def test_tenant_route_assigns_only_that_tenants_card(self, start_followups):
        second = create_tenant()
        second_card = create_physical_card(second, number=12)
        marta_card = PhysicalCard.objects.get(code="MB-12")
        data = {**REGISTRATION_DATA, "barcode": "SC-12"}

        response = self.client.post(
            reverse("dotykacka:tenant_register", args=[second.slug]),
            data,
        )

        self.assertEqual(response.status_code, 302)
        customer = Klient.objects.get(klient_id="SC-12")
        self.assertEqual(customer.tenant, second)
        second_card.refresh_from_db()
        marta_card.refresh_from_db()
        self.assertEqual(second_card.customer, customer)
        self.assertEqual(second_card.status, PhysicalCard.Status.ASSIGNED)
        self.assertIsNone(marta_card.customer)
        self.assertEqual(marta_card.status, PhysicalCard.Status.AVAILABLE)
        start_followups.assert_called_once_with(customer.pk)

    def test_tenant_route_rejects_another_tenants_prefix_and_inventory(self):
        second = create_tenant()
        create_physical_card(second, number=12)

        response = self.client.post(
            reverse("dotykacka:tenant_register", args=[second.slug]),
            REGISTRATION_DATA,
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(Klient.objects.filter(tenant=second).exists())


class IntegrationSettingsSecurityTests(TestCase):
    def setUp(self):
        self.tenant = default_tenant()
        self.owner = create_tenant_owner(self.tenant)
        self.url = reverse(
            "dotykacka:integration_settings",
            args=[self.tenant.slug],
        )

    def test_owner_can_view_settings_without_secret_disclosure(self):
        connection = configure_dotykacka(self.tenant)
        self.client.force_login(self.owner)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Token: skonfigurowany")
        self.assertNotContains(response, "authorization-token")
        self.assertNotIn("authorization-token", connection.credentials_encrypted)

    def test_blank_secret_retains_encrypted_value_and_audits_update(self):
        key = Fernet.generate_key().decode("ascii")
        with override_settings(TENANT_SECRETS_ENCRYPTION_KEYS=[key]):
            connection = configure_dotykacka(self.tenant)
            encrypted_before = connection.credentials_encrypted
            self.client.force_login(self.owner)

            response = self.client.post(
                self.url,
                {
                    "provider": IntegrationConnection.Provider.DOTYKACKA,
                    "enabled": "on",
                    "cloud_id": "987",
                    "discount_group_id": "654",
                    "authorization_token": "",
                },
            )

            self.assertRedirects(response, self.url)
            connection.refresh_from_db()
            self.assertEqual(connection.configuration["cloud_id"], 987)
            self.assertEqual(connection.get_secret("authorization_token"), "authorization-token")
            self.assertTrue(connection.credentials_encrypted.startswith("fernet:v1:"))
            self.assertNotIn("authorization-token", connection.credentials_encrypted)
            self.assertTrue(encrypted_before.startswith("fernet:v1:"))

        event = AuditEvent.objects.get(action="integration.updated")
        self.assertEqual(event.tenant, self.tenant)
        self.assertEqual(event.actor, self.owner)
        self.assertEqual(event.metadata["provider"], "dotykacka")
        self.assertNotIn("authorization-token", json.dumps(event.metadata))

    def test_non_owner_cannot_manage_tenant_integrations(self):
        other_tenant = create_tenant()
        other_owner = create_tenant_owner(other_tenant, username="other-owner")
        self.client.force_login(other_owner)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 403)

    def test_staff_membership_cannot_change_owner_only_integrations(self):
        staff = get_user_model().objects.create_user(
            username="tenant-staff",
            password="test-only-password",
        )
        TenantMembership.objects.create(
            tenant=self.tenant,
            user=staff,
            role=TenantMembership.Role.STAFF,
        )
        self.client.force_login(staff)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 403)

    def test_platform_superuser_can_manage_tenant_integrations(self):
        self.client.force_login(create_superuser())

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
