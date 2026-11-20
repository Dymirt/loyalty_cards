import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock
from uuid import uuid4

from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from billing.models import UsageEvent
from billing.tests.test_billing_services import create_subscription
from customers.models import ConsentRecord, Customer
from dotykacka.models import PhysicalCard, WalletPass
from dotykacka.tests.base import (
    configure_brevo,
    configure_dotykacka,
    configure_google_wallet,
    create_tenant,
    create_tenant_owner,
)
from dotykacka.tests.test_card_designs import create_design
from enrollment.models import (
    VirtualCardApiKey,
    VirtualCardApplication,
    VirtualCardFollowUp,
)
from enrollment.links import url_for_virtual_apple_pass
from communications.services import send_pass_email
from integrations.models import IntegrationJob
from wallet_apple.services import issuer as apple_issuer
from wallet_google.services import issuer as google_issuer


@override_settings(
    APPLE_WALLET_PASS_TYPE_IDENTIFIER="pass.example.loyalty",
    APPLE_WALLET_TEAM_IDENTIFIER="TEAM123",
)
class VirtualCardApiTests(TestCase):
    def setUp(self):
        self.media = TemporaryDirectory()
        self.override_media = override_settings(MEDIA_ROOT=self.media.name)
        self.override_media.enable()
        self.addCleanup(self.override_media.disable)
        self.addCleanup(self.media.cleanup)
        self.tenant = create_tenant(
            name="Atelier Café",
            slug="atelier-cafe-api",
            card_prefix="ACV",
        )
        self.design_one = create_design(self.tenant, version=1, front_text="Atelier Gold")
        self.design_two = create_design(self.tenant, version=2, front_text="Atelier Noir")
        self.api_key, self.raw_key = VirtualCardApiKey.issue(
            tenant=self.tenant,
            name="Website backend",
        )
        self.headers = {"HTTP_AUTHORIZATION": f"Bearer {self.raw_key}"}
        self.payload = {
            "first_name": "Anna",
            "last_name": "Nowak",
            "email": "anna@example.test",
            "phone": "+48500100200",
            "card_design_id": self.design_one.pk,
            "marketing_consent": True,
        }

    def post_card(self, *, payload=None, key="checkout-request-0001"):
        return self.client.post(
            reverse("virtual_cards_api:create"),
            data=json.dumps(payload or self.payload),
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY=key,
            **self.headers,
        )

    def test_design_api_lists_only_the_authenticated_tenant_designs(self):
        other = create_tenant(name="Other", slug="other-virtual", card_prefix="OVC")
        create_design(other)

        response = self.client.get(
            reverse("virtual_cards_api:designs"),
            **self.headers,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [item["id"] for item in response.json()["results"]],
            [self.design_two.pk, self.design_one.pk],
        )
        self.assertIn("background_url", response.json()["results"][0])
        self.assertIn("preview_url", response.json()["results"][0])
        preview = self.client.get(response.json()["results"][0]["preview_url"])
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(preview["Content-Type"], "image/jpeg")

    def test_design_catalog_exposes_only_four_newest_choices(self):
        design_three = create_design(self.tenant, version=3, front_text="Third")
        design_four = create_design(self.tenant, version=4, front_text="Fourth")
        design_five = create_design(self.tenant, version=5, front_text="Fifth")

        response = self.client.get(
            reverse("virtual_cards_api:designs"),
            **self.headers,
        )

        self.assertEqual(
            [item["id"] for item in response.json()["results"]],
            [design_five.pk, design_four.pk, design_three.pk, self.design_two.pk],
        )
        rejected = self.post_card()
        self.assertEqual(rejected.status_code, 400)
        self.assertEqual(rejected.json()["error"]["code"], "invalid_card_design")

    def test_api_creates_only_virtual_identity_and_wallet_email_jobs(self):
        configure_dotykacka(self.tenant)
        configure_brevo(self.tenant)
        create_subscription(self.tenant)

        response = self.post_card()

        self.assertEqual(response.status_code, 202)
        self.assertNotIn("google_wallet_url", response.json())
        self.assertNotIn("apple_wallet_url", response.json())
        application = VirtualCardApplication.objects.get(tenant=self.tenant)
        customer = Customer.objects.get(pk=application.customer_id)
        self.assertTrue(response.json()["card"]["created"])
        self.assertTrue(response.json()["card_created"])
        self.assertEqual(response.json()["card_id"], customer.klient_id)
        self.assertEqual(
            response.json()["delivery"]["apple_wallet"]["status"],
            IntegrationJob.Status.PENDING,
        )
        self.assertEqual(
            response.json()["delivery"]["google_wallet"]["status"],
            "not_requested",
        )
        wallet = WalletPass.objects.get(customer=customer)
        self.assertEqual(wallet.card_design, self.design_one)
        self.assertFalse(PhysicalCard.objects.filter(customer=customer).exists())
        self.assertTrue(customer.klient_id.startswith("ACV-V-"))
        self.assertEqual(application.usage_event.kind, UsageEvent.Kind.VIRTUAL_CARD_ISSUED)
        self.assertTrue(ConsentRecord.objects.get(customer=customer).granted)
        self.assertSetEqual(
            set(VirtualCardFollowUp.objects.values_list("kind", flat=True)),
            {"wallet.apple.issue", "communications.email.pass"},
        )

        status = self.client.get(
            response.json()["status_url"],
            **self.headers,
        )
        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.json()["request_id"], response.json()["request_id"])
        self.assertEqual(status.json()["card_id"], customer.klient_id)

        wallet.apple_pass_path = "wallets/issued.pkpass"
        wallet.save(update_fields=("apple_pass_path", "updated_at"))
        IntegrationJob.objects.filter(
            virtual_card_followup__application=application
        ).update(status=IntegrationJob.Status.SUCCEEDED)
        completed = self.client.get(
            response.json()["status_url"],
            **self.headers,
        )
        self.assertEqual(completed.json()["state"], "email_sent")
        self.assertTrue(completed.json()["delivery"]["apple_wallet"]["ready"])
        self.assertTrue(completed.json()["delivery"]["email"]["ready"])

    def test_virtual_email_has_apple_button_and_download_link(self):
        response = self.post_card()
        application = VirtualCardApplication.objects.select_related(
            "customer__wallet_pass"
        ).get(public_id=response.json()["request_id"])
        wallet = application.customer.wallet_pass
        relative_path = Path("wallets") / "virtual-test.pkpass"
        pass_path = Path(self.media.name) / relative_path
        pass_path.parent.mkdir(parents=True)
        pass_path.write_bytes(b"signed-pass")
        wallet.apple_pass_path = relative_path.as_posix()
        wallet.save(update_fields=("apple_pass_path", "updated_at"))
        apple_url = url_for_virtual_apple_pass(application)

        sent = send_pass_email(
            application.customer,
            brand_snapshot=application.brand_snapshot,
            apple_wallet_url=apple_url,
        )

        self.assertEqual(sent, 1)
        self.assertIn("Dodaj do Apple Wallet", mail.outbox[0].alternatives[0].content)
        self.assertIn(apple_url, mail.outbox[0].alternatives[0].content)
        self.assertEqual(mail.outbox[0].attachments[0].filename, "loyalty-card.pkpass")
        download = self.client.get(apple_url)
        self.assertEqual(download.status_code, 200)
        self.assertEqual(download["Content-Type"], "application/vnd.apple.pkpass")

    def test_idempotency_replays_same_result_and_rejects_changed_data(self):
        first = self.post_card()
        second = self.post_card()
        changed = dict(self.payload, first_name="Different")
        conflict = self.post_card(payload=changed)

        self.assertEqual(first.status_code, 202)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.json()["request_id"], second.json()["request_id"])
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(conflict.json()["error"]["code"], "idempotency_conflict")
        self.assertEqual(VirtualCardApplication.objects.count(), 1)
        self.assertEqual(Customer.objects.filter(tenant=self.tenant).count(), 1)

    @override_settings(GOOGLE_WALLET_ISSUER_ID="123456789")
    def test_selected_design_is_used_by_both_wallet_issuers(self):
        configure_google_wallet(self.tenant)
        response = self.post_card()
        customer = VirtualCardApplication.objects.get(
            public_id=response.json()["request_id"]
        ).customer
        apple_designs = []

        def apple_builder(*, customer, wallet, design):
            apple_designs.append(design)
            return Path(self.media.name) / "virtual.pkpass", object()

        apple_issuer.issue(
            customer,
            builder=apple_builder,
            updater=lambda wallet, artifact: None,
        )
        url_builder = Mock(return_value="https://wallet.example.test/save")
        google_issuer.issue(
            customer,
            url_builder=url_builder,
            remote_sync=False,
        )

        self.assertEqual(apple_designs, [self.design_one])
        self.assertEqual(
            url_builder.call_args.kwargs["class_suffix"],
            f"{self.tenant.card_prefix}.d{self.design_one.pk}",
        )
        self.assertIn(
            reverse(
                "enrollment:virtual_card_design_asset",
                args=[self.tenant.slug, self.design_one.pk, "background"],
            ),
            url_builder.call_args.kwargs["customer_image_url"],
        )

    def test_cross_tenant_design_and_revoked_keys_are_rejected(self):
        other = create_tenant(name="Other", slug="other-design", card_prefix="ODV")
        other_design = create_design(other)
        invalid_design = self.post_card(
            payload=dict(self.payload, card_design_id=other_design.pk)
        )
        self.api_key.revoke()
        revoked = self.post_card(key="checkout-request-0002")

        self.assertEqual(invalid_design.status_code, 400)
        self.assertEqual(invalid_design.json()["error"]["code"], "invalid_card_design")
        self.assertEqual(revoked.status_code, 401)
        self.assertEqual(VirtualCardApplication.objects.count(), 0)

    def test_public_form_uses_selected_design_and_only_confirms_email_delivery(self):
        response = self.client.post(
            reverse("enrollment:virtual_card_form", args=[self.tenant.slug]),
            {
                "first_name": "Maria",
                "last_name": "Kowalska",
                "email": "maria@example.test",
                "phone": "501234567",
                "card_design": self.design_two.pk,
                "marketing_consent": "on",
                "request_id": str(uuid4()),
            },
        )

        self.assertEqual(response.status_code, 201)
        self.assertContains(response, "maria@example.test", status_code=201)
        application = VirtualCardApplication.objects.get(source="public_form")
        self.assertEqual(application.card_design, self.design_two)
        self.assertIsNone(application.api_key)
        self.assertNotContains(response, "pay.google.com", status_code=201)


class VirtualCardApiKeyPortalTests(TestCase):
    def setUp(self):
        self.tenant = create_tenant(
            name="Marta Banaszek Atelier Café",
            slug="marta-virtual-api",
            card_prefix="MBV",
        )
        self.owner = create_tenant_owner(self.tenant, username="marta-virtual-owner")
        self.client.force_login(self.owner)

    def test_owner_can_create_key_once_and_revoke_it(self):
        response = self.client.post(
            reverse("enrollment:virtual_card_api_keys", args=[self.tenant.slug]),
            {"name": "Atelier website"},
        )

        self.assertEqual(response.status_code, 201)
        key = VirtualCardApiKey.objects.get(tenant=self.tenant)
        self.assertContains(response, VirtualCardApiKey.TOKEN_PREFIX, status_code=201)
        rendered = response.content.decode("utf-8")
        raw_fragment = rendered.split(VirtualCardApiKey.TOKEN_PREFIX, 1)[1].split("<", 1)[0]
        raw_key = VirtualCardApiKey.TOKEN_PREFIX + raw_fragment
        self.assertNotEqual(raw_key, key.token_hash)
        self.assertNotIn(raw_key, key.token_hash)

        revoked = self.client.post(
            reverse(
                "enrollment:revoke_virtual_card_api_key",
                args=[self.tenant.slug, key.pk],
            )
        )

        self.assertEqual(revoked.status_code, 302)
        key.refresh_from_db()
        self.assertIsNotNone(key.revoked_at)

    def test_other_tenant_owner_cannot_manage_keys(self):
        other = create_tenant(name="Other", slug="other-key-owner", card_prefix="OKV")
        key, _raw = VirtualCardApiKey.issue(tenant=other, name="Other key")

        self.assertEqual(
            self.client.get(
                reverse("enrollment:virtual_card_api_keys", args=[other.slug])
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(
                reverse(
                    "enrollment:revoke_virtual_card_api_key",
                    args=[other.slug, key.pk],
                )
            ).status_code,
            403,
        )
