from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from billing.models import EntitlementPolicy, Plan, PlanVersion, TenantSubscription
from billing.services import publish_plan_version
from tenants.models import Tenant, TenantMembership


class BillingViewTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(
            name="Tenant",
            slug="tenant",
            card_prefix="TV",
        )
        self.owner = get_user_model().objects.create_user("owner", password="password")
        self.staff = get_user_model().objects.create_user("staff", password="password")
        self.superuser = get_user_model().objects.create_superuser(
            "platform", "platform@example.com", "password"
        )
        TenantMembership.objects.create(
            tenant=self.tenant,
            user=self.owner,
            role=TenantMembership.Role.OWNER,
        )
        TenantMembership.objects.create(
            tenant=self.tenant,
            user=self.staff,
            role=TenantMembership.Role.STAFF,
        )

    def test_owner_sees_unmanaged_compatibility_and_cannot_publish_commercial_data(self):
        self.client.force_login(self.owner)

        tenant_response = self.client.get(
            reverse("billing:tenant", args=[self.tenant.slug])
        )
        platform_response = self.client.get(reverse("billing:platform"))

        self.assertContains(tenant_response, "Tryb zgodności")
        self.assertEqual(platform_response.status_code, 302)

    def test_staff_cannot_access_owner_billing(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse("billing:tenant", args=[self.tenant.slug]))
        self.assertEqual(response.status_code, 403)

    def test_platform_operator_can_open_publication_dashboard(self):
        self.client.force_login(self.superuser)
        response = self.client.get(reverse("billing:platform"))
        self.assertContains(response, "Plany, ceny i subskrypcje")

    def test_owner_quote_post_supports_htmx_error_response(self):
        plan = Plan.objects.create(code="owner", name="Owner")
        version = PlanVersion.objects.create(
            plan=plan,
            version=1,
            recurring_amount=Decimal("10.00"),
            currency="PLN",
        )
        EntitlementPolicy.objects.create(plan_version=version)
        publish_plan_version(plan_version=version)
        TenantSubscription.objects.create(
            tenant=self.tenant,
            plan_version=version,
            status=TenantSubscription.Status.ACTIVE,
            starts_at=timezone.now() - timedelta(days=1),
        )
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse("billing:create_quote", args=[self.tenant.slug]),
            {"quantity": 10, "price_book_version": "", "idempotency_key": "view"},
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "Nie udało się obliczyć ceny", status_code=400)
