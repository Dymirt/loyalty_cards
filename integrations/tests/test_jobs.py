from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from integrations.contracts import RetryableIntegrationError
from integrations.models import IntegrationJob
from integrations.registry import register_job_handler
from integrations.services import claim_next_job, enqueue_job, fail_job

from dotykacka.tests.base import create_tenant


class DurableJobTests(TestCase):
    def test_enqueue_is_idempotent_and_payload_rejects_secrets(self):
        tenant = create_tenant()
        first = enqueue_job(
            tenant=tenant,
            kind="test.noop",
            idempotency_key="same-key",
            payload={"customer_id": 1},
        )
        second = enqueue_job(
            tenant=tenant,
            kind="test.noop",
            idempotency_key="same-key",
            payload={"customer_id": 1},
        )
        self.assertEqual(first.pk, second.pk)
        with self.assertRaises(ValueError):
            enqueue_job(
                tenant=tenant,
                kind="test.noop",
                idempotency_key="secret-key",
                payload={"api_key": "must-not-be-stored"},
            )

    def test_retryable_failure_is_available_after_backoff(self):
        tenant = create_tenant()
        enqueue_job(
            tenant=tenant,
            kind="test.retry",
            idempotency_key="retry",
            payload={"customer_id": 1},
        )
        job = claim_next_job(worker_id="worker-a")
        fail_job(
            job,
            RetryableIntegrationError(error_code="rate_limited", retry_after=19),
        )
        job.refresh_from_db()
        self.assertEqual(job.status, IntegrationJob.Status.RETRY)
        self.assertEqual(job.last_error_code, "rate_limited")
        self.assertGreater(job.available_at, timezone.now())
        self.assertIsNone(claim_next_job(worker_id="worker-b"))

    def test_stale_running_job_is_reclaimed_after_process_restart(self):
        tenant = create_tenant()
        job = enqueue_job(
            tenant=tenant,
            kind="test.recover",
            idempotency_key="recover",
            payload={"customer_id": 1},
        )
        job.status = IntegrationJob.Status.RUNNING
        job.locked_by = "dead-process"
        job.locked_at = timezone.now() - timedelta(minutes=10)
        job.save()
        claimed = claim_next_job(worker_id="replacement")
        self.assertEqual(claimed.pk, job.pk)
        self.assertEqual(claimed.locked_by, "replacement")
        self.assertEqual(claimed.attempts, 1)

    def test_management_command_executes_claimed_job(self):
        tenant = create_tenant()
        seen = []

        def handler(job):
            seen.append(job.pk)

        register_job_handler("test.command", handler)
        job = enqueue_job(
            tenant=tenant,
            kind="test.command",
            idempotency_key="command",
            payload={"customer_id": 1},
        )
        stdout = StringIO()
        call_command("run_integration_worker", once=True, stdout=stdout)
        job.refresh_from_db()
        self.assertEqual(seen, [job.pk])
        self.assertEqual(job.status, IntegrationJob.Status.SUCCEEDED)
        self.assertIn("processed=1", stdout.getvalue())
