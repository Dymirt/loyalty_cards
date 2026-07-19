from uuid import uuid4

from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import resolve, reverse

from customers.models import Customer
from dotykacka.tests.base import create_tenant, create_tenant_owner
from marketing.models import MarketingLead


def lead_payload(**overrides):
    payload = {
        "full_name": "Jan Kowalski",
        "company_name": "Kawiarnia Testowa",
        "email": "JAN@EXAMPLE.TEST",
        "phone": "501 234 567",
        "message": "Potrzebujemy programu dla dwóch lokali.",
        "privacy_consent": "on",
        "submission_id": str(uuid4()),
        "website": "",
    }
    payload.update(overrides)
    return payload


@override_settings(
    MARKETING_PRIVACY_VERSION="test-policy-v1",
    MARKETING_PRIVACY_CONSENT_TEXT="Test consent text.",
)
class MarketingViewTests(TestCase):
    def test_all_public_pages_render_without_javascript_or_authentication(self):
        pages = (
            "marketing:home",
            "marketing:features",
            "marketing:integrations",
            "marketing:pricing",
            "marketing:contact",
            "marketing:privacy",
            "marketing:terms",
        )
        for name in pages:
            with self.subTest(name=name):
                response = self.client.get(reverse(name))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "/static/css/portal.v1.css")
                self.assertContains(response, reverse("login"))
                self.assertNotContains(response, "unpkg.com")

    def test_marketing_pages_do_not_expose_tenant_or_customer_data(self):
        tenant = create_tenant(
            name="SECRET TENANT NAME",
            slug="secret-marketing-tenant",
            card_prefix="SMT",
        )
        owner = create_tenant_owner(tenant, username="secret-marketing-owner")
        Customer.objects.create(
            tenant=tenant,
            klient_id="SMT-1",
            email="secret-customer@example.test",
            first_name="SecretCustomerName",
        )
        self.client.force_login(owner)

        for name in ("marketing:home", "marketing:pricing", "marketing:features"):
            response = self.client.get(reverse(name))
            self.assertNotContains(response, "SECRET TENANT NAME")
            self.assertNotContains(response, "secret-customer@example.test")
            self.assertNotContains(response, "SecretCustomerName")

    def test_empty_catalog_states_that_prices_are_not_published(self):
        response = self.client.get(reverse("marketing:pricing"))

        self.assertContains(response, "Cennik w przygotowaniu")
        self.assertContains(response, "wyłącznie zatwierdzone")

    def test_legacy_routes_redirect_without_turnkey_app_runtime(self):
        home = reverse("marketing:home")
        for path in ("/turnkey/", "/marketing/"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 301)
            self.assertEqual(response.url, home)
        self.assertEqual(resolve("/turnkey/").func.__module__, "marketing.views")

    def test_plain_post_records_one_normalized_idempotent_lead(self):
        payload = lead_payload()

        first = self.client.post(reverse("marketing:contact"), payload)
        second = self.client.post(reverse("marketing:contact"), payload)

        self.assertRedirects(first, reverse("marketing:contact_thanks"))
        self.assertRedirects(second, reverse("marketing:contact_thanks"))
        self.assertEqual(MarketingLead.objects.count(), 1)
        lead = MarketingLead.objects.get()
        self.assertEqual(lead.email, "jan@example.test")
        self.assertEqual(lead.privacy_policy_version, "test-policy-v1")
        self.assertEqual(len(lead.privacy_text_sha256), 64)
        self.assertEqual(lead.source_path, reverse("marketing:contact"))

    def test_reused_submission_id_with_different_content_is_rejected(self):
        payload = lead_payload()
        self.client.post(reverse("marketing:contact"), payload)

        response = self.client.post(
            reverse("marketing:contact"),
            {**payload, "message": "Different content"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(MarketingLead.objects.count(), 1)
        self.assertContains(response, "identifier was already used", status_code=400)

    def test_htmx_post_returns_success_fragment_and_invalid_form_swaps_errors(self):
        success = self.client.post(
            reverse("marketing:contact"),
            lead_payload(),
            HTTP_HX_REQUEST="true",
        )
        invalid = self.client.post(
            reverse("marketing:contact"),
            lead_payload(privacy_consent=""),
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(success.status_code, 200)
        self.assertContains(success, 'id="contact-form"')
        self.assertContains(success, "Zapytanie zapisane")
        self.assertEqual(invalid.status_code, 200)
        self.assertContains(invalid, "To pole jest wymagane")
        self.assertEqual(MarketingLead.objects.count(), 1)

    def test_honeypot_and_missing_consent_do_not_create_leads(self):
        for payload in (
            lead_payload(website="https://spam.example"),
            lead_payload(privacy_consent=""),
        ):
            response = self.client.post(reverse("marketing:contact"), payload)
            self.assertEqual(response.status_code, 400)
        self.assertEqual(MarketingLead.objects.count(), 0)

    def test_lead_history_cannot_be_rewritten_or_deleted(self):
        self.client.post(reverse("marketing:contact"), lead_payload())
        lead = MarketingLead.objects.get()
        lead.message = "Changed"

        with self.assertRaises(ValidationError):
            lead.save()
        with self.assertRaises(ValidationError):
            lead.delete()
