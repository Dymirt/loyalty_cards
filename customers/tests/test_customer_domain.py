from django.core.exceptions import ValidationError
from django.test import TestCase

from customers.models import ConsentRecord, Customer, CustomerExternalIdentity
from customers.services import record_marketing_consent
from dotykacka.tests.base import create_klient, create_tenant


class CustomerDomainTests(TestCase):
    def test_customer_alias_keeps_legacy_model_and_table(self):
        self.assertEqual(Customer._meta.label_lower, "dotykacka.klient")
        self.assertEqual(Customer._meta.db_table, "dotykacka_klient")

    def test_consent_evidence_is_hashed_and_append_only(self):
        customer = create_klient()
        record = record_marketing_consent(customer=customer, consent_text="Test consent")

        self.assertEqual(record.tenant, customer.tenant)
        self.assertEqual(len(record.consent_text_sha256), 64)
        record.source = "changed"
        with self.assertRaises(ValidationError):
            record.save()
        with self.assertRaises(ValidationError):
            record.delete()

    def test_external_identity_validates_tenant_ownership(self):
        customer = create_klient()
        other = create_tenant(name="Other", slug="other", card_prefix="OT")
        identity = CustomerExternalIdentity(
            tenant=other,
            customer=customer,
            provider="dotykacka",
            remote_id="remote-1",
        )
        with self.assertRaises(ValidationError):
            identity.full_clean()
        self.assertEqual(
            identity.sync_status,
            CustomerExternalIdentity.SyncStatus.PENDING,
        )
        self.assertEqual(ConsentRecord.objects.filter(customer=customer).count(), 0)

    def test_pending_identity_does_not_require_a_remote_id(self):
        first = create_klient()
        second = create_klient("MB-13")
        first_identity = CustomerExternalIdentity.objects.create(
            tenant=first.tenant,
            customer=first,
            provider="dotykacka",
        )
        second_identity = CustomerExternalIdentity.objects.create(
            tenant=second.tenant,
            customer=second,
            provider="dotykacka",
        )

        self.assertIsNone(first_identity.remote_id)
        self.assertIsNone(second_identity.remote_id)
        self.assertEqual(first_identity.sync_status, "pending")
