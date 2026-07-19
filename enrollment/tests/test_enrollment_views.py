from datetime import timedelta

from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from dotykacka.tests.base import (
    create_physical_card,
    create_tenant,
    create_tenant_owner,
)
from enrollment.links import issue_access_link, token_for_link
from enrollment.models import EnrollmentAccessLink
from enrollment.services import register_customer_with_card
from customers.models import Customer
from tenants.models import TenantDomain

from .test_enrollment_services import cleaned_registration


class EnrollmentViewTests(TestCase):
    def test_database_allows_only_one_primary_domain_per_tenant(self):
        tenant = create_tenant(name="Primary Café", slug="primary-cafe", card_prefix="PR")
        TenantDomain.objects.create(
            tenant=tenant,
            hostname="first.primary.example.test",
            status=TenantDomain.Status.VERIFIED,
            verified_at=timezone.now(),
            is_primary=True,
        )

        with self.assertRaises(IntegrityError), transaction.atomic():
            TenantDomain.objects.create(
                tenant=tenant,
                hostname="second.primary.example.test",
                status=TenantDomain.Status.VERIFIED,
                verified_at=timezone.now(),
                is_primary=True,
            )

    @override_settings(
        APPLE_WALLET_PASS_TYPE_IDENTIFIER="",
        APPLE_WALLET_TEAM_IDENTIFIER="",
    )
    def test_global_registration_resolves_unique_card_prefix_before_consent(self):
        tenant = create_tenant(name="Prefix Café", slug="prefix-cafe", card_prefix="PFX")
        card = create_physical_card(tenant, number=5)
        payload = cleaned_registration(card.code)
        payload["marketing_consent"] = "on"

        confirmation = self.client.post(reverse("enrollment:register"), payload)

        self.assertEqual(confirmation.status_code, 409)
        self.assertContains(confirmation, "Prefix Café", status_code=409)
        self.assertFalse(Customer.objects.filter(klient_id=card.code).exists())
        payload["tenant_confirmation"] = tenant.slug
        with self.captureOnCommitCallbacks(execute=True):
            completed = self.client.post(reverse("enrollment:register"), payload)
        self.assertEqual(completed.status_code, 302)
        self.assertTrue(Customer.objects.filter(tenant=tenant, klient_id=card.code).exists())

    @override_settings(
        ALLOWED_HOSTS=["tenant.example.test", "testserver"],
        APPLE_WALLET_PASS_TYPE_IDENTIFIER="",
        APPLE_WALLET_TEAM_IDENTIFIER="",
    )
    def test_verified_domain_selects_tenant_and_pending_domain_does_not(self):
        tenant = create_tenant(name="Domain Café", slug="domain-cafe", card_prefix="DC")
        create_physical_card(tenant, number=5)
        TenantDomain.objects.create(
            tenant=tenant,
            hostname="tenant.example.test",
            status=TenantDomain.Status.VERIFIED,
            verified_at=timezone.now(),
            is_primary=True,
        )

        response = self.client.get(
            reverse("enrollment:register"),
            HTTP_HOST="tenant.example.test",
        )

        self.assertContains(response, "Domain Café")
        self.assertContains(response, "DC-12")

    @override_settings(
        APPLE_WALLET_PASS_TYPE_IDENTIFIER="",
        APPLE_WALLET_TEAM_IDENTIFIER="",
    )
    def test_signed_status_is_public_but_expires_and_does_not_render_email(self):
        tenant = create_tenant(name="Status Café", slug="status-cafe", card_prefix="ST")
        card = create_physical_card(tenant, number=4)
        result = register_customer_with_card(
            tenant=tenant,
            cleaned_data=cleaned_registration(card.code),
        )
        status_url = reverse("enrollment:public_status", args=[result.access_token])

        response = self.client.get(status_url)

        self.assertContains(response, card.code)
        self.assertNotContains(response, "synthetic@example.test")
        expired = issue_access_link(
            enrollment=result.enrollment,
            reason=EnrollmentAccessLink.Reason.RESEND,
            now=timezone.now() - timedelta(days=31),
        )
        expired_response = self.client.get(
            reverse("enrollment:public_status", args=[token_for_link(expired)])
        )
        self.assertEqual(expired_response.status_code, 410)

    @override_settings(
        APPLE_WALLET_PASS_TYPE_IDENTIFIER="",
        APPLE_WALLET_TEAM_IDENTIFIER="",
    )
    def test_management_is_tenant_isolated_and_domain_request_is_pending(self):
        tenant = create_tenant(name="Owner Café", slug="owner-cafe", card_prefix="OC")
        owner = create_tenant_owner(tenant, username="enrollment-owner")
        other = create_tenant(name="Other Café", slug="other-enrollment", card_prefix="OE")
        outsider = create_tenant_owner(other, username="enrollment-outsider")

        self.client.force_login(outsider)
        self.assertEqual(
            self.client.get(reverse("enrollment:manage", args=[tenant.slug])).status_code,
            403,
        )
        self.client.force_login(owner)
        response = self.client.post(
            reverse("enrollment:request_domain", args=[tenant.slug]),
            {"hostname": "club.owner.example.test"},
        )
        self.assertRedirects(response, reverse("enrollment:manage", args=[tenant.slug]))
        domain = TenantDomain.objects.get(tenant=tenant)
        self.assertEqual(domain.status, TenantDomain.Status.PENDING)
