"""Platform operations, health and append-only alert evidence."""

from uuid import uuid4

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class RateLimitBucket(models.Model):
    scope = models.CharField(max_length=80)
    identity_hash = models.CharField(max_length=64)
    window_started_at = models.DateTimeField()
    request_count = models.PositiveIntegerField(default=0)
    limited_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("scope", "identity_hash", "window_started_at"),
                name="operations_unique_rate_limit_window",
            )
        ]
        indexes = [
            models.Index(
                fields=("scope", "window_started_at"),
                name="operations_rate_window_idx",
            )
        ]

    def delete(self, *args, **kwargs):
        raise ValidationError("Rate-limit evidence cannot be deleted.")


class WorkerHeartbeat(models.Model):
    class WorkerType(models.TextChoices):
        INTEGRATION = "integration", "Integration worker"
        PRINTING = "printing", "Print worker"
        MONITOR = "monitor", "Operations monitor"

    worker_type = models.CharField(max_length=24, choices=WorkerType.choices)
    worker_id = models.CharField(max_length=160)
    started_at = models.DateTimeField(default=timezone.now)
    last_seen_at = models.DateTimeField(default=timezone.now, db_index=True)
    processed_count = models.PositiveBigIntegerField(default=0)
    status = models.CharField(max_length=32, default="running")
    safe_metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("worker_type", "worker_id"),
                name="operations_unique_worker_heartbeat",
            )
        ]
        indexes = [
            models.Index(
                fields=("worker_type", "last_seen_at"),
                name="operations_worker_seen_idx",
            )
        ]

    def delete(self, *args, **kwargs):
        raise ValidationError("Worker heartbeat history cannot be deleted.")


class OperationalAlert(models.Model):
    class Severity(models.TextChoices):
        WARNING = "warning", "Warning"
        CRITICAL = "critical", "Critical"

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        ACKNOWLEDGED = "acknowledged", "Acknowledged"
        RESOLVED = "resolved", "Resolved"

    public_id = models.UUIDField(default=uuid4, unique=True, editable=False)
    fingerprint = models.CharField(max_length=191, unique=True)
    category = models.CharField(max_length=48, db_index=True)
    severity = models.CharField(max_length=16, choices=Severity.choices)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.OPEN,
        db_index=True,
    )
    tenant = models.ForeignKey(
        "dotykacka.Tenant",
        on_delete=models.PROTECT,
        related_name="operational_alerts",
        blank=True,
        null=True,
    )
    title = models.CharField(max_length=180)
    safe_summary = models.TextField(max_length=1000)
    source_type = models.CharField(max_length=80, blank=True)
    source_id = models.CharField(max_length=120, blank=True)
    occurrences = models.PositiveIntegerField(default=1)
    first_seen_at = models.DateTimeField(default=timezone.now)
    last_seen_at = models.DateTimeField(default=timezone.now)
    acknowledged_at = models.DateTimeField(blank=True, null=True)
    acknowledged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="acknowledged_operational_alerts",
        blank=True,
        null=True,
    )
    resolved_at = models.DateTimeField(blank=True, null=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="resolved_operational_alerts",
        blank=True,
        null=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("status", "-severity", "-last_seen_at", "-pk")

    def delete(self, *args, **kwargs):
        raise ValidationError("Operational alerts cannot be deleted.")


class OperationalAlertEvent(models.Model):
    class Kind(models.TextChoices):
        DETECTED = "detected", "Detected"
        SEEN = "seen", "Seen again"
        ACKNOWLEDGED = "acknowledged", "Acknowledged"
        RESOLVED = "resolved", "Resolved"
        REOPENED = "reopened", "Reopened"

    alert = models.ForeignKey(
        OperationalAlert,
        on_delete=models.PROTECT,
        related_name="events",
    )
    kind = models.CharField(max_length=24, choices=Kind.choices)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="operational_alert_events",
        blank=True,
        null=True,
    )
    reason = models.TextField(max_length=1000, blank=True)
    safe_snapshot = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("created_at", "pk")

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("Operational alert events are append-only.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Operational alert events cannot be deleted.")


__all__ = [
    "OperationalAlert",
    "OperationalAlertEvent",
    "RateLimitBucket",
    "WorkerHeartbeat",
]
