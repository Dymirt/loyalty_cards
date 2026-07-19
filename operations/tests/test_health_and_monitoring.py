from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from dotykacka.tests.base import default_tenant
from integrations.models import IntegrationJob
from operations.models import OperationalAlert, OperationalAlertEvent, WorkerHeartbeat
from operations.monitoring import scan_operational_alerts
from operations.services import acknowledge_alert, record_worker_heartbeat, resolve_alert


class HealthAndMonitoringTests(TestCase):
    def _heartbeats(self, now=None):
        for worker_type in WorkerHeartbeat.WorkerType.values:
            record_worker_heartbeat(
                worker_type=worker_type,
                worker_id=f"test-{worker_type}",
            )
        if now:
            WorkerHeartbeat.objects.update(last_seen_at=now)

    def test_liveness_is_public_and_redacted(self):
        response = self.client.get(reverse("health_live"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})
        self.assertEqual(response["Cache-Control"], "no-store")

    def test_readiness_checks_database_storage_and_worker_heartbeats(self):
        with TemporaryDirectory() as media, TemporaryDirectory() as printing, override_settings(
            MEDIA_ROOT=media,
            PRINT_PACKAGE_ROOT=Path(printing),
            WORKER_HEARTBEAT_MAX_AGE_SECONDS=90,
        ):
            self._heartbeats()
            response = self.client.get(reverse("health_ready"))
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {"status": "ok"})

            WorkerHeartbeat.objects.filter(
                worker_type=WorkerHeartbeat.WorkerType.PRINTING
            ).update(last_seen_at=timezone.now() - timedelta(minutes=10))
            degraded = self.client.get(reverse("health_ready"))
            self.assertEqual(degraded.status_code, 503)
            self.assertEqual(degraded.json(), {"status": "degraded"})
            self.assertNotContains(degraded, "printing", status_code=503)

    def test_operations_dashboard_is_superuser_only(self):
        url = reverse("operations:dashboard")
        self.assertEqual(self.client.get(url).status_code, 302)
        user = get_user_model().objects.create_superuser(
            username="operator",
            email="operator@example.test",
            password="strong-password",
        )
        self.client.force_login(user)
        with TemporaryDirectory() as media, TemporaryDirectory() as printing, override_settings(
            MEDIA_ROOT=media,
            PRINT_PACKAGE_ROOT=Path(printing),
        ):
            self._heartbeats()
            response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Stan operacyjny")
        self.assertNotContains(response, "credentials_encrypted")

    def test_failed_job_creates_one_alert_and_later_resolves_it(self):
        tenant = default_tenant()
        self._heartbeats()
        job = IntegrationJob.objects.create(
            tenant=tenant,
            kind="test.provider",
            idempotency_key="monitor-test",
            status=IntegrationJob.Status.FAILED,
            last_error_code="provider_failure",
        )
        first_now = timezone.now()
        first = scan_operational_alerts(now=first_now)
        self.assertGreaterEqual(first["active"], 1)
        alert = OperationalAlert.objects.get(fingerprint=f"integration-job:{job.pk}")
        self.assertEqual(alert.status, OperationalAlert.Status.OPEN)
        self.assertEqual(
            alert.events.get().kind,
            OperationalAlertEvent.Kind.DETECTED,
        )

        job.status = IntegrationJob.Status.SUCCEEDED
        job.save(update_fields=("status", "updated_at"))
        scan_operational_alerts(now=first_now + timedelta(seconds=2))
        alert.refresh_from_db()
        self.assertEqual(alert.status, OperationalAlert.Status.RESOLVED)
        self.assertEqual(alert.events.last().kind, OperationalAlertEvent.Kind.RESOLVED)

    def test_alert_acknowledgement_and_resolution_append_events(self):
        tenant = default_tenant()
        user = get_user_model().objects.create_superuser(
            username="alert-admin",
            email="alert@example.test",
            password="strong-password",
        )
        alert = OperationalAlert.objects.create(
            fingerprint="manual:test",
            category="test",
            severity=OperationalAlert.Severity.WARNING,
            tenant=tenant,
            title="Test alert",
            safe_summary="Safe summary",
        )
        acknowledge_alert(alert=alert, actor=user, reason="Sprawdzam przyczynę")
        resolve_alert(alert=alert, actor=user, reason="Przyczyna usunięta")
        alert.refresh_from_db()
        self.assertEqual(alert.status, OperationalAlert.Status.RESOLVED)
        self.assertEqual(
            list(alert.events.values_list("kind", flat=True)),
            [
                OperationalAlertEvent.Kind.ACKNOWLEDGED,
                OperationalAlertEvent.Kind.RESOLVED,
            ],
        )

