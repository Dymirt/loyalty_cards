"""Provider-neutral integration state and durable jobs.

The historical ``IntegrationConnection`` table remains owned by ``dotykacka``
until a separately approved state migration. New jobs are created directly in
their final app and contain identifiers only, never provider secrets.
"""

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from dotykacka.models import IntegrationConnection


class IntegrationJob(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        RETRY = "retry", "Retry scheduled"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"

    tenant = models.ForeignKey(
        "dotykacka.Tenant",
        on_delete=models.PROTECT,
        related_name="integration_jobs",
    )
    connection = models.ForeignKey(
        "dotykacka.IntegrationConnection",
        on_delete=models.PROTECT,
        related_name="jobs",
        blank=True,
        null=True,
    )
    kind = models.CharField(max_length=100, db_index=True)
    idempotency_key = models.CharField(max_length=220)
    payload = models.JSONField(default=dict, blank=True)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    attempts = models.PositiveSmallIntegerField(default=0)
    max_attempts = models.PositiveSmallIntegerField(default=5)
    available_at = models.DateTimeField(default=timezone.now, db_index=True)
    locked_at = models.DateTimeField(blank=True, null=True)
    locked_by = models.CharField(max_length=120, blank=True)
    finished_at = models.DateTimeField(blank=True, null=True)
    last_error_code = models.CharField(max_length=80, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("tenant", "idempotency_key"),
                name="unique_tenant_integration_job_key",
            )
        ]
        indexes = [
            models.Index(
                fields=("status", "available_at", "created_at"),
                name="integration_job_claim_idx",
            )
        ]
        ordering = ("created_at", "pk")

    def clean(self):
        if self.connection_id and self.connection.tenant_id != self.tenant_id:
            raise ValidationError(
                {"connection": "Job and integration connection must share a tenant."}
            )
        if self.attempts > self.max_attempts:
            raise ValidationError({"attempts": "Attempts cannot exceed max attempts."})

    def delete(self, *args, **kwargs):
        raise ValidationError("Integration job history cannot be deleted.")


__all__ = ["IntegrationConnection", "IntegrationJob"]
