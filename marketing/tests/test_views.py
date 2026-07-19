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
                self.assertContains(response, "/static/css/portal.v1.css?v=3")
                self.assertContains(response, reverse("login"))
                self.assertNotContains(response, "unpkg.com")

    def test_marketing_pages_do_not_expose_tenant_or_customer_data(self):
        tenant = create_tenant(
            name="SECRET TENANT NAME",
            slug="secret-marketing-tenant",
            card_prefix="SMT",
        )
        tenant.public_registration_enabled = False
        tenant.save(update_fields=("public_registration_enabled", "updated_at"))
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

    def test_home_links_only_active_public_tenant_registration_programs(self):
        public_tenant = create_tenant(
            name="Publiczna Kawiarnia",
            slug="publiczna-kawiarnia",
            card_prefix="PK",
        )
        public_tenant.brand.tagline = "Klub stałych gości"
        public_tenant.brand.logo_path = "public-program-logo.png"
        public_tenant.brand.save(update_fields=("tagline", "logo_path", "updated_at"))
        Customer.objects.create(
            tenant=public_tenant,
            klient_id="PK-1",
            email="private-program-customer@example.test",
            first_name="PrivateProgramCustomer",
        )

        disabled_tenant = create_tenant(
            name="Rejestracja Wyłączona",
            slug="rejestracja-wylaczona",
            card_prefix="RW",
        )
        disabled_tenant.public_registration_enabled = False
        disabled_tenant.save(
            update_fields=("public_registration_enabled", "updated_at")
        )

        inactive_tenant = create_tenant(
            name="Firma Nieaktywna",
            slug="firma-nieaktywna",
            card_prefix="FN",
        )
        inactive_tenant.is_active = False
        inactive_tenant.save(update_fields=("is_active", "updated_at"))

        response = self.client.get(reverse("marketing:home"))

        self.assertContains(response, "Masz kartę jednej z naszych firm?")
        self.assertContains(response, "Publiczna Kawiarnia")
        self.assertContains(response, "Klub stałych gości")
        self.assertContains(response, "public-program-logo.png")
        self.assertContains(
            response,
            reverse("enrollment:tenant_register", args=[public_tenant.slug]),
        )
        self.assertNotContains(response, "Rejestracja Wyłączona")
        self.assertNotContains(response, "Firma Nieaktywna")
        self.assertNotContains(response, "private-program-customer@example.test")
        self.assertNotContains(response, "PrivateProgramCustomer")

    def test_empty_catalog_states_that_prices_are_not_published(self):
        response = self.client.get(reverse("marketing:pricing"))

        self.assertContains(response, "Cennik w przygotowaniu")
        self.assertContains(response, "przygotowujemy ofertę indywidualnie")
        self.assertContains(response, "Decyzja bez automatycznej opłaty")

    def test_public_sales_journey_uses_benefits_instead_of_implementation_details(self):
        home = self.client.get(reverse("marketing:home"))
        features = self.client.get(reverse("marketing:features"))
        integrations = self.client.get(reverse("marketing:integrations"))

        self.assertContains(home, "Zamieniaj pierwszą wizytę")
        self.assertContains(home, "Porozmawiajmy o Twoim programie")
        self.assertContains(home, "Strefa posiadacza karty")
        self.assertContains(features, "Korzyść odczuwa klient, zespół i właściciel")
        self.assertContains(integrations, "Program dopasowany do tego, jak już pracujesz")
        for response in (features, integrations):
            self.assertNotContains(response, "Lokalne dane są źródłem prawdy")
            self.assertNotContains(response, "renderowane przez Django")
            self.assertNotContains(response, "Adapter zamiast przebudowy")

    def test_every_sales_page_has_one_consistent_contact_path(self):
        for name in (
            "marketing:home",
            "marketing:features",
            "marketing:integrations",
            "marketing:pricing",
            "marketing:contact",
        ):
            with self.subTest(name=name):
                response = self.client.get(reverse(name))
                self.assertContains(response, reverse("marketing:contact"))
                self.assertContains(response, "Zapytaj o wdrożenie")

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
        self.assertContains(
            response,
            "Identyfikator tego zgłoszenia kontaktowego został już użyty.",
            status_code=400,
        )

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
