from django.test import TestCase, override_settings
from django.urls import reverse

from customers.models import CustomerExportApiToken
from dotykacka.models import AuditEvent
from dotykacka.tests.base import (
    create_klient,
    create_superuser,
    create_tenant,
    create_tenant_owner,
)


@override_settings(
    CUSTOMER_EXPORT_API_IP_RATE_LIMIT=100,
    CUSTOMER_EXPORT_API_TOKEN_RATE_LIMIT=100,
    CUSTOMER_EXPORT_API_RATE_LIMIT_WINDOW_SECONDS=60,
)
class CustomerExportApiTests(TestCase):
    def setUp(self):
        self.customer = create_klient(
            email="anna@example.test",
            first_name="Anna",
            last_name="Nowak",
        )
        self.tenant = self.customer.tenant
        self.token, self.raw_token = CustomerExportApiToken.issue(
            tenant=self.tenant,
            name="CRM klienta",
        )
        self.url = reverse("customers_api:clients")
        self.authorization = {"HTTP_AUTHORIZATION": f"Bearer {self.raw_token}"}

    def test_token_secret_is_hashed_at_rest(self):
        self.assertTrue(self.raw_token.startswith(CustomerExportApiToken.TOKEN_PREFIX))
        self.assertNotEqual(self.token.token_hash, self.raw_token)
        self.assertEqual(
            self.token.token_hash,
            CustomerExportApiToken.digest(self.raw_token),
        )

    def test_requires_a_valid_bearer_token(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            response["WWW-Authenticate"],
            'Bearer realm="customer-export"',
        )
        self.assertEqual(response["Cache-Control"], "no-store")

        response = self.client.get(
            self.url,
            HTTP_AUTHORIZATION="Bearer invalid",
        )
        self.assertEqual(response.status_code, 401)

    def test_returns_only_emailed_customers_from_the_token_tenant(self):
        create_klient("MB-13", email=None)
        other_tenant = create_tenant()
        create_klient(
            "SC-12",
            tenant=other_tenant,
            email="other@example.test",
        )

        response = self.client.get(self.url, **self.authorization)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertEqual(response.json()["count"], 1)
        self.assertEqual(
            response.json()["results"],
            [
                {
                    "client_id": self.customer.klient_id,
                    "first_name": "Anna",
                    "last_name": "Nowak",
                    "phone": "501234567",
                    "email": "anna@example.test",
                }
            ],
        )
        self.token.refresh_from_db()
        self.assertIsNotNone(self.token.last_used_at)

    def test_revoked_token_is_rejected(self):
        self.token.revoke()
        response = self.client.get(self.url, **self.authorization)
        self.assertEqual(response.status_code, 401)

    def test_inactive_tenant_token_is_rejected(self):
        self.tenant.is_active = False
        self.tenant.save(update_fields=("is_active", "updated_at"))
        response = self.client.get(self.url, **self.authorization)
        self.assertEqual(response.status_code, 401)

    def test_pagination_and_parameter_validation(self):
        create_klient("MB-13", email="second@example.test")
        response = self.client.get(
            f"{self.url}?page_size=1",
            **self.authorization,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 2)
        self.assertIsNotNone(response.json()["next"])

        response = self.client.get(
            f"{self.url}?page_size=501",
            **self.authorization,
        )
        self.assertEqual(response.status_code, 400)

        response = self.client.get(
            f"{self.url}?page=999",
            **self.authorization,
        )
        self.assertEqual(response.status_code, 404)

    def test_only_get_is_allowed(self):
        response = self.client.post(self.url, **self.authorization)
        self.assertEqual(response.status_code, 405)

    @override_settings(CUSTOMER_EXPORT_API_TOKEN_RATE_LIMIT=1)
    def test_token_rate_limit_returns_retry_after(self):
        first = self.client.get(self.url, **self.authorization)
        second = self.client.get(self.url, **self.authorization)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 429)
        self.assertIn("Retry-After", second)
        self.assertEqual(second["Cache-Control"], "no-store")


class CustomerExportApiTokenAdminTests(TestCase):
    def setUp(self):
        self.customer = create_klient()
        self.tenant = self.customer.tenant
        self.admin_user = create_superuser()
        self.client.force_login(self.admin_user)

    def test_admin_creates_audits_and_displays_token_once(self):
        response = self.client.post(
            reverse("admin:customers_customerexportapitoken_add"),
            {"tenant": self.tenant.pk, "name": "System księgowy"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, CustomerExportApiToken.TOKEN_PREFIX)
        token = CustomerExportApiToken.objects.get(name="System księgowy")
        self.assertEqual(token.created_by, self.admin_user)
        self.assertNotContains(response, token.token_hash)
        self.assertTrue(
            AuditEvent.objects.filter(
                tenant=self.tenant,
                actor=self.admin_user,
                action="customer_export_api_token.created",
                object_id=str(token.pk),
            ).exists()
        )

    def test_admin_revokes_and_audits_token(self):
        token, _ = CustomerExportApiToken.issue(
            tenant=self.tenant,
            name="System klienta",
            created_by=self.admin_user,
        )
        response = self.client.post(
            reverse("admin:customers_customerexportapitoken_changelist"),
            {
                "action": "revoke_selected",
                "_selected_action": [str(token.pk)],
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        token.refresh_from_db()
        self.assertIsNotNone(token.revoked_at)
        self.assertTrue(
            AuditEvent.objects.filter(
                action="customer_export_api_token.revoked",
                object_id=str(token.pk),
            ).exists()
        )

    def test_tenant_owner_sees_only_owned_tenant_tokens(self):
        owned_token, _ = CustomerExportApiToken.issue(
            tenant=self.tenant,
            name="Owned integration",
        )
        other_tenant = create_tenant()
        CustomerExportApiToken.issue(
            tenant=other_tenant,
            name="Other integration",
        )
        owner = create_tenant_owner(self.tenant)
        owner.is_staff = True
        owner.save(update_fields=("is_staff",))
        self.client.force_login(owner)

        response = self.client.get(
            reverse("admin:customers_customerexportapitoken_changelist")
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, owned_token.name)
        self.assertNotContains(response, "Other integration")
