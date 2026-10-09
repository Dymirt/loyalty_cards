import json
from datetime import timedelta
from io import BytesIO
from unittest.mock import Mock, patch

from PIL import Image
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from communications.ai import generate_campaign_copy
from communications.campaigns import (
    eligible_campaign_customers,
    generate_campaign_content,
    schedule_campaign,
)
from communications.jobs import send_campaign_email_job
from communications.models import (
    CampaignAsset,
    CampaignRecipient,
    CommunicationDelivery,
    EmailCampaign,
)
from customers.services import record_marketing_consent
from dotykacka.models import PhysicalCard
from dotykacka.tests.base import (
    create_klient,
    create_physical_card,
    create_tenant,
    create_tenant_owner,
)
from integrations.models import IntegrationConnection


def assigned_customer(tenant, *, number, consent=True, email=None):
    card = create_physical_card(tenant, number=number)
    customer = create_klient(
        card.code,
        tenant,
        email=email or f"customer-{number}@example.test",
    )
    card.customer = customer
    card.status = PhysicalCard.Status.ASSIGNED
    card.save(update_fields=("customer", "status"))
    if consent:
        record_marketing_consent(
            customer=customer,
            consent_text="Zgoda na komunikację marketingową",
        )
    return customer


def image_upload(name="material.png", color=(154, 60, 31)):
    content = BytesIO()
    Image.new("RGB", (320, 200), color).save(content, format="PNG")
    return SimpleUploadedFile(name, content.getvalue(), content_type="image/png")


class CampaignAudienceAndDeliveryTests(TestCase):
    def setUp(self):
        self.tenant = create_tenant(name="Marta Banaszek", slug="marta", card_prefix="MBX")
        self.owner = create_tenant_owner(self.tenant, username="marta-owner")
        self.customer = assigned_customer(self.tenant, number=1)
        assigned_customer(self.tenant, number=2, consent=False)
        create_klient("MBX-99", self.tenant, email="no-card@example.test")
        self.campaign = EmailCampaign.objects.create(
            tenant=self.tenant,
            created_by=self.owner,
            name="Jesienne śniadania",
            goal="Zaproś gości na jesienne śniadania i podwójne punkty w weekend.",
            reference_links=["https://example.test/menu"],
        )

    def test_audience_contains_only_assigned_cardholders_with_current_consent(self):
        self.assertEqual(list(eligible_campaign_customers(self.tenant)), [self.customer])

    def test_schedule_freezes_recipients_and_creates_due_jobs(self):
        generate_campaign_content(self.campaign)
        scheduled_for = timezone.now() + timedelta(hours=2)

        campaign = schedule_campaign(
            campaign=self.campaign,
            scheduled_for=scheduled_for,
        )

        self.assertEqual(campaign.status, EmailCampaign.Status.SCHEDULED)
        self.assertEqual(campaign.recipient_count, 1)
        recipient = CampaignRecipient.objects.get(campaign=campaign)
        self.assertEqual(recipient.customer, self.customer)
        self.assertEqual(recipient.email_snapshot, self.customer.email)
        self.assertEqual(recipient.integration_job.available_at, scheduled_for)
        self.assertEqual(
            recipient.integration_job.payload,
            {"campaign_recipient_id": recipient.pk},
        )

    @patch("communications.jobs.send_campaign_email", return_value=1)
    def test_campaign_job_is_idempotent_and_updates_campaign_totals(self, send_email):
        generate_campaign_content(self.campaign)
        campaign = schedule_campaign(
            campaign=self.campaign,
            scheduled_for=timezone.now() + timedelta(minutes=5),
        )
        recipient = CampaignRecipient.objects.get(campaign=campaign)

        send_campaign_email_job(recipient.integration_job)
        send_campaign_email_job(recipient.integration_job)

        recipient.refresh_from_db()
        campaign.refresh_from_db()
        self.assertEqual(recipient.status, CampaignRecipient.Status.SENT)
        self.assertEqual(campaign.status, EmailCampaign.Status.SENT)
        self.assertEqual(campaign.sent_count, 1)
        self.assertEqual(campaign.failed_count, 0)
        self.assertEqual(
            CommunicationDelivery.objects.get(integration_job=recipient.integration_job).status,
            CommunicationDelivery.Status.SENT,
        )
        send_email.assert_called_once()


class CampaignViewsTests(TestCase):
    def setUp(self):
        self.tenant = create_tenant(name="Studio Marta", slug="studio-marta", card_prefix="SM")
        self.owner = create_tenant_owner(self.tenant, username="studio-owner")
        assigned_customer(self.tenant, number=3)
        self.client.force_login(self.owner)

    def test_owner_can_save_generate_and_preview_a_campaign_with_an_image(self):
        response = self.client.post(
            reverse("communications:new", args=[self.tenant.slug]),
            {
                "goal": "Poinformuj o nowym menu. <script>alert(1)</script>",
                "links": "https://example.test/menu",
                "images": [image_upload()],
                "action": "generate",
            },
        )

        campaign = EmailCampaign.objects.get(tenant=self.tenant)
        self.assertRedirects(
            response,
            reverse("communications:edit", args=[self.tenant.slug, campaign.pk]),
        )
        self.assertEqual(campaign.generation_source, EmailCampaign.GenerationSource.LOCAL)
        self.assertNotIn("<script>", campaign.html_content)
        self.assertIn("&lt;script&gt;", campaign.html_content)
        self.assertEqual(CampaignAsset.objects.filter(campaign=campaign).count(), 1)
        preview = self.client.get(
            reverse("communications:preview", args=[self.tenant.slug, campaign.pk])
        )
        self.assertEqual(preview.status_code, 200)
        self.assertContains(preview, reverse(
            "communications:asset",
            args=[self.tenant.slug, campaign.pk, campaign.assets.get().pk],
        ))

    def test_campaigns_are_isolated_between_tenants(self):
        other = create_tenant(name="Other", slug="other", card_prefix="OT")
        campaign = EmailCampaign.objects.create(
            tenant=other,
            created_by=create_tenant_owner(other, username="other-owner"),
            name="Other campaign",
            goal="Other goal",
        )

        self.assertEqual(
            self.client.get(reverse("communications:list", args=[other.slug])).status_code,
            403,
        )
        self.assertEqual(
            self.client.get(
                reverse("communications:edit", args=[other.slug, campaign.pk])
            ).status_code,
            403,
        )

    def test_schedule_action_uses_the_current_tenant_audience(self):
        scheduled = timezone.localtime() + timedelta(hours=1)
        response = self.client.post(
            reverse("communications:new", args=[self.tenant.slug]),
            {
                "goal": "Przypomnij o wydarzeniu dla stałych klientów.",
                "links": "",
                "scheduled_for": scheduled.strftime("%Y-%m-%dT%H:%M"),
                "action": "schedule",
            },
        )

        self.assertRedirects(
            response,
            reverse("communications:list", args=[self.tenant.slug]),
        )
        campaign = EmailCampaign.objects.get(tenant=self.tenant)
        self.assertEqual(campaign.status, EmailCampaign.Status.SCHEDULED)
        self.assertEqual(campaign.recipient_count, 1)


class OpenAIIntegrationTests(TestCase):
    def setUp(self):
        self.tenant = create_tenant(name="AI Café", slug="ai-cafe", card_prefix="AI")
        self.owner = create_tenant_owner(self.tenant, username="ai-owner")
        self.client.force_login(self.owner)

    def test_openai_key_is_saved_encrypted_from_integration_settings(self):
        response = self.client.post(
            reverse("integrations:settings", args=[self.tenant.slug]),
            {
                "provider": "openai",
                "openai-enabled": "on",
                "openai-model": "gpt-6-luna",
                "openai-api_key": "sk-test-tenant-secret",
            },
        )

        self.assertEqual(response.status_code, 302)
        connection = IntegrationConnection.objects.get(
            tenant=self.tenant,
            provider="openai",
        )
        self.assertTrue(connection.enabled)
        self.assertEqual(connection.get_secret("api_key"), "sk-test-tenant-secret")
        self.assertNotIn("sk-test-tenant-secret", connection.credentials_encrypted)
        settings_page = self.client.get(
            reverse("integrations:settings", args=[self.tenant.slug])
        )
        self.assertContains(settings_page, "Klucz API OpenAI")
        self.assertNotContains(settings_page, "sk-test-tenant-secret")
        self.assertContains(
            settings_page,
            reverse("integrations:test", args=[self.tenant.slug, "openai"]),
        )

    @patch("communications.ai.requests.get")
    def test_owner_can_test_the_openai_connection(self, get_request):
        connection = IntegrationConnection.objects.create(
            tenant=self.tenant,
            provider="openai",
            enabled=True,
            configuration={"model": "gpt-6-luna"},
        )
        connection.set_credentials({"api_key": "sk-test"})
        connection.save(update_fields=("credentials_encrypted",))
        response = Mock(status_code=200)
        response.json.return_value = {"data": [{"id": "gpt-6-luna"}]}
        get_request.return_value = response

        result = self.client.post(
            reverse("integrations:test", args=[self.tenant.slug, "openai"]),
            follow=True,
        )

        self.assertContains(result, "Połączenie działa.")
        connection.refresh_from_db()
        self.assertIsNotNone(connection.last_success_at)
        self.assertEqual(connection.last_error_code, "")
        self.assertEqual(
            get_request.call_args.kwargs["headers"]["Authorization"],
            "Bearer sk-test",
        )

    @override_settings(OPENAI_EMAIL_MODEL="gpt-6-luna")
    def test_structured_openai_copy_is_used_without_accepting_arbitrary_html(self):
        connection = IntegrationConnection.objects.create(
            tenant=self.tenant,
            provider="openai",
            enabled=True,
            configuration={"model": "gpt-6-luna"},
        )
        connection.set_credentials({"api_key": "sk-test"})
        connection.save(update_fields=("credentials_encrypted",))
        campaign = EmailCampaign.objects.create(
            tenant=self.tenant,
            created_by=self.owner,
            name="AI draft",
            goal="Zaproś na śniadanie.",
            reference_links=["https://example.test/breakfast"],
        )
        generated = {
            "subject": "Śniadanie czeka",
            "preheader": "Nowe smaki dla stałych gości",
            "headline": "Spotkajmy się przy śniadaniu",
            "body_paragraphs": ["Mamy nowe menu.", "Wpadnij w ten weekend."],
            "cta_label": "Zobacz menu",
            "cta_url_index": 0,
            "accent_color": "#A43F24",
            "background_color": "#F6F1E8",
        }
        response = Mock(status_code=200)
        response.json.return_value = {
            "output": [
                {
                    "type": "message",
                    "content": [
                        {"type": "output_text", "text": json.dumps(generated)}
                    ],
                }
            ]
        }
        session = Mock()
        session.post.return_value = response

        copy, model = generate_campaign_copy(campaign, session=session)

        self.assertEqual(copy["subject"], "Śniadanie czeka")
        self.assertEqual(model, "gpt-6-luna")
        payload = session.post.call_args.kwargs["json"]
        self.assertEqual(payload["text"]["format"]["type"], "json_schema")
        self.assertFalse(payload["store"])
