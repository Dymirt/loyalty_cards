from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase

from customers.models import CustomerExternalIdentity
from integrations.contracts import IntegrationError, RetryableIntegrationError
from integrations.models import IntegrationJob
from pos_dotykacka.jobs import CUSTOMER_UPSERT_JOB, upsert_customer_job

from dotykacka.tests.base import configure_dotykacka, create_klient, create_tenant


class DotykackaCustomerJobTests(TestCase):
    def setUp(self):
        self.tenant = create_tenant()
        self.connection = configure_dotykacka(self.tenant)
        self.customer = create_klient("SC-21", tenant=self.tenant)

    def _job(self, **overrides):
        values = {
            "tenant": self.tenant,
            "connection": self.connection,
            "kind": CUSTOMER_UPSERT_JOB,
            "idempotency_key": f"customer:{self.customer.pk}",
            "payload": {"customer_id": self.customer.pk},
            "status": IntegrationJob.Status.RUNNING,
            "attempts": 1,
            "max_attempts": 5,
        }
        values.update(overrides)
        return IntegrationJob.objects.create(**values)

    @patch("pos_dotykacka.jobs.adapter_for_tenant")
    def test_terminal_provider_error_marks_external_identity_failed(self, adapter_factory):
        adapter_factory.return_value.upsert_customer.side_effect = IntegrationError(
            error_code="dotykacka_http_400"
        )
        job = self._job()

        with self.assertRaises(IntegrationError):
            upsert_customer_job(job)

        identity = CustomerExternalIdentity.objects.get(customer=self.customer)
        self.assertEqual(identity.sync_status, CustomerExternalIdentity.SyncStatus.FAILED)
        self.assertEqual(identity.last_error_code, "dotykacka_http_400")
        self.assertIsNotNone(identity.last_attempted_at)

    @patch("pos_dotykacka.jobs.adapter_for_tenant")
    def test_retryable_provider_error_keeps_external_identity_pending(self, adapter_factory):
        adapter_factory.return_value.upsert_customer.side_effect = RetryableIntegrationError(
            error_code="dotykacka_http_503"
        )
        job = self._job()

        with self.assertRaises(RetryableIntegrationError):
            upsert_customer_job(job)

        identity = CustomerExternalIdentity.objects.get(customer=self.customer)
        self.assertEqual(identity.sync_status, CustomerExternalIdentity.SyncStatus.PENDING)
        self.assertEqual(identity.last_error_code, "dotykacka_http_503")


class RetryFailedCustomerSyncsCommandTests(TestCase):
    def setUp(self):
        self.tenant = create_tenant()
        self.connection = configure_dotykacka(self.tenant)
        self.customer = create_klient("SC-22", tenant=self.tenant)

    def _failed_job(self, *, error_code="HTTPError", kind=CUSTOMER_UPSERT_JOB):
        return IntegrationJob.objects.create(
            tenant=self.tenant,
            connection=self.connection,
            kind=kind,
            idempotency_key=f"{kind}:{error_code}",
            payload={"customer_id": self.customer.pk},
            status=IntegrationJob.Status.FAILED,
            attempts=1,
            max_attempts=5,
            last_error_code=error_code,
        )

    def test_command_is_dry_run_by_default_and_only_requeues_selected_failures(self):
        target = self._failed_job()
        other_code = self._failed_job(error_code="dotykacka_http_403")
        other_kind = self._failed_job(kind="wallet.google.issue")
        stdout = StringIO()

        call_command("retry_failed_customer_syncs", stdout=stdout)

        target.refresh_from_db()
        self.assertEqual(target.status, IntegrationJob.Status.FAILED)
        self.assertIn(f"matched=1 job_ids={target.pk}", stdout.getvalue())
        self.assertIn("dry-run", stdout.getvalue())

        stdout = StringIO()
        call_command("retry_failed_customer_syncs", apply=True, stdout=stdout)

        target.refresh_from_db()
        other_code.refresh_from_db()
        other_kind.refresh_from_db()
        self.assertEqual(target.status, IntegrationJob.Status.RETRY)
        self.assertEqual(other_code.status, IntegrationJob.Status.FAILED)
        self.assertEqual(other_kind.status, IntegrationJob.Status.FAILED)
        self.assertIn("requeued=1", stdout.getvalue())
