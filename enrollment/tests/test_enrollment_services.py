from datetime import timedelta

from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from billing.models import UsageEvent
from billing.tests.test_billing_services import create_subscription
from customers.models import ConsentRecord, Customer
from dotykacka.tests.base import (
    REGISTRATION_DATA,
    configure_brevo,
    configure_dotykacka,
    configure_google_wallet,
    create_physical_card,
    create_tenant,
    create_tenant_owner,
    default_tenant,
)
from enrollment.jobs import enqueue_enrollment_followups
from enrollment.links import (
    EnrollmentLinkExpired,
    issue_access_link,
    resolve_access_link,
    token_for_link,
)
from enrollment.models import (
    Enrollment,
    EnrollmentAccessLink,
    EnrollmentEvent,
    EnrollmentFollowUp,
)
from enrollment.services import (
    registration_brand_for_tenant,
    register_customer_with_card,
    resend_enrollment_email,
    retry_enrollment_followup,
)
from integrations.models import IntegrationJob


def cleaned_registration(code):
    return {
        "barcode": code,
        "first_name": "Synthetic",
        "last_name": "Customer",
        "email": "synthetic@example.test",
        "phone": "501234567",
        "marketing_consent": True,
    }


class EnrollmentServiceTests(TestCase):
    def test_registration_uses_the_public_web_background_not_the_card_master(self):
        tenant = default_tenant()
        design = tenant.card_designs.get(version=1)
        self.assertNotEqual(
            tenant.brand.background_image_path,
            design.background_source.name,
        )

        release = registration_brand_for_tenant(tenant)

        self.assertEqual(
            release["background_image_path"],
            tenant.brand.background_image_path,
        )

    def test_registration_uses_domain_services_and_records_consent(self):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                reverse("enrollment:register"),
                REGISTRATION_DATA,
            )

        self.assertEqual(response.status_code, 302)
        customer = Customer.objects.get(klient_id="MB-12")
        self.assertEqual(customer.physical_card.code, "MB-12")
        consent = ConsentRecord.objects.get(customer=customer)
        self.assertTrue(consent.granted)
        self.assertEqual(consent.purpose, "marketing")
        enrollment = Enrollment.objects.get(customer=customer)
        self.assertEqual(enrollment.physical_card, customer.physical_card)
        self.assertGreaterEqual(enrollment.events.count(), 4)
        self.assertTrue(
            enrollment.events.filter(
                kind=EnrollmentEvent.Kind.ISSUANCE_RECORDED
            ).exists()
        )

    @override_settings(
        APPLE_WALLET_PASS_TYPE_IDENTIFIER="",
        APPLE_WALLET_TEAM_IDENTIFIER="",
    )
    def test_commit_freezes_brand_consent_and_links_managed_issuance(self):
        tenant = create_tenant(name="Frozen Brand", slug="frozen-brand", card_prefix="FB")
        card = create_physical_card(tenant, number=7)
        create_subscription(tenant)

        result = register_customer_with_card(
            tenant=tenant,
            cleaned_data=cleaned_registration(card.code),
        )

        enrollment = result.enrollment
        self.assertEqual(enrollment.brand_snapshot["public_name"], "Frozen Brand")
        self.assertEqual(enrollment.consent_record.policy_version, "live-brand")
        self.assertEqual(enrollment.usage_event.kind, UsageEvent.Kind.PHYSICAL_CARD_ISSUED)
        self.assertEqual(resolve_access_link(result.access_token).enrollment, enrollment)
        enrollment.brand_snapshot = {"public_name": "Changed"}
        with self.assertRaises(ValidationError):
            enrollment.save()

    @override_settings(
        APPLE_WALLET_PASS_TYPE_IDENTIFIER="",
        APPLE_WALLET_TEAM_IDENTIFIER="",
    )
    def test_followup_creation_is_post_commit_and_idempotent(self):
        tenant = create_tenant(name="Jobs Café", slug="jobs-cafe", card_prefix="JC")
        card = create_physical_card(tenant, number=3)
        configure_dotykacka(tenant)
        configure_brevo(tenant)
        configure_google_wallet(tenant)

        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            result = register_customer_with_card(
                tenant=tenant,
                cleaned_data=cleaned_registration(card.code),
            )

        self.assertEqual(len(callbacks), 1)
        self.assertEqual(result.enrollment.followups.count(), 4)
        first_jobs = list(
            result.enrollment.followups.values_list("integration_job_id", flat=True)
        )
        enqueue_enrollment_followups(result.enrollment.pk)
        self.assertEqual(result.enrollment.followups.count(), 4)
        self.assertEqual(
            list(result.enrollment.followups.values_list("integration_job_id", flat=True)),
            first_jobs,
        )
        self.assertFalse(
            IntegrationJob.objects.filter(payload__has_key="api_key").exists()
        )

    @override_settings(
        APPLE_WALLET_PASS_TYPE_IDENTIFIER="",
        APPLE_WALLET_TEAM_IDENTIFIER="",
    )
    def test_retry_reuses_job_and_resend_creates_one_explicit_generation(self):
        tenant = create_tenant(name="Retry Café", slug="retry-cafe", card_prefix="RC")
        owner = create_tenant_owner(tenant, username="retry-owner")
        card = create_physical_card(tenant, number=8)
        configure_dotykacka(tenant)
        configure_google_wallet(tenant)
        with self.captureOnCommitCallbacks(execute=True):
            enrollment = register_customer_with_card(
                tenant=tenant,
                cleaned_data=cleaned_registration(card.code),
            ).enrollment

        pos_followup = enrollment.followups.get(kind="pos.dotykacka.customer_upsert")
        IntegrationJob.objects.filter(pk=pos_followup.integration_job_id).update(
            status=IntegrationJob.Status.FAILED,
            attempts=5,
            max_attempts=5,
        )
        pos_followup.integration_job.refresh_from_db()
        job, created = retry_enrollment_followup(
            followup=pos_followup,
            actor=owner,
            idempotency_key="retry-action-1",
            reason="Connection repaired",
        )
        repeated, repeated_created = retry_enrollment_followup(
            followup=pos_followup,
            actor=owner,
            idempotency_key="retry-action-1",
            reason="Connection repaired",
        )
        self.assertTrue(created)
        self.assertFalse(repeated_created)
        self.assertEqual(job.pk, repeated.pk)
        self.assertEqual(job.status, IntegrationJob.Status.RETRY)
        self.assertGreater(job.max_attempts, job.attempts)

        resend, resend_created = resend_enrollment_email(
            enrollment=enrollment,
            actor=owner,
            idempotency_key="resend-action-1",
            reason="Customer requested another message",
        )
        resend_again, resend_again_created = resend_enrollment_email(
            enrollment=enrollment,
            actor=owner,
            idempotency_key="resend-action-1",
            reason="Customer requested another message",
        )
        self.assertTrue(resend_created)
        self.assertFalse(resend_again_created)
        self.assertEqual(resend.pk, resend_again.pk)
        self.assertEqual(resend.generation, 2)
        self.assertEqual(
            EnrollmentAccessLink.objects.filter(enrollment=enrollment).count(),
            2,
        )

    def test_expired_access_link_is_rejected_without_mutating_history(self):
        tenant = create_tenant(name="Expiry Café", slug="expiry-cafe", card_prefix="EC")
        card = create_physical_card(tenant, number=2)
        enrollment = register_customer_with_card(
            tenant=tenant,
            cleaned_data=cleaned_registration(card.code),
        ).enrollment
        link = issue_access_link(
            enrollment=enrollment,
            reason=EnrollmentAccessLink.Reason.REGISTRATION,
            now=timezone.now() - timedelta(days=31),
        )
        link_count = enrollment.access_links.count()

        with self.assertRaises(EnrollmentLinkExpired):
            resolve_access_link(token_for_link(link))
        self.assertEqual(enrollment.access_links.count(), link_count)
