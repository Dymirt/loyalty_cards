"""Durable communication-delivery evidence."""

from django.core.exceptions import ValidationError
from django.db import models


class CommunicationDelivery(models.Model):
    """One guarded email attempt; ambiguous outcomes are never auto-replayed."""

    class Channel(models.TextChoices):
        EMAIL = "email", "Email"

    class Status(models.TextChoices):
        SENDING = "sending", "Sending"
        SENT = "sent", "Sent"
        OUTCOME_UNKNOWN = "outcome_unknown", "Outcome unknown"

    tenant = models.ForeignKey(
        "dotykacka.Tenant",
        on_delete=models.PROTECT,
        related_name="communication_deliveries",
    )
    customer = models.ForeignKey(
        "dotykacka.Klient",
        on_delete=models.PROTECT,
        related_name="communication_deliveries",
    )
    integration_job = models.OneToOneField(
        "integrations.IntegrationJob",
        on_delete=models.PROTECT,
        related_name="communication_delivery",
    )
    channel = models.CharField(
        max_length=16,
        choices=Channel.choices,
        default=Channel.EMAIL,
    )
    template_key = models.CharField(max_length=80, default="loyalty-card-ready-v1")
    generation = models.PositiveIntegerField(default=1)
    recipient_sha256 = models.CharField(max_length=64)
    subject_snapshot = models.CharField(max_length=240)
    status = models.CharField(
        max_length=24,
        choices=Status.choices,
        default=Status.SENDING,
        db_index=True,
    )
    started_at = models.DateTimeField()
    completed_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at", "-pk")

    def clean(self):
        errors = {}
        if self.customer_id and self.customer.tenant_id != self.tenant_id:
            errors["customer"] = "Customer and delivery must share a tenant."
        if self.integration_job_id and self.integration_job.tenant_id != self.tenant_id:
            errors["integration_job"] = "Job and delivery must share a tenant."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.pk:
            previous = type(self).objects.get(pk=self.pk)
            immutable = (
                "tenant_id",
                "customer_id",
                "integration_job_id",
                "channel",
                "template_key",
                "generation",
                "recipient_sha256",
                "subject_snapshot",
                "started_at",
            )
            if any(getattr(previous, name) != getattr(self, name) for name in immutable):
                raise ValidationError("Communication delivery terms are immutable.")
            allowed = {
                self.Status.SENDING: {self.Status.SENT, self.Status.OUTCOME_UNKNOWN},
                self.Status.SENT: set(),
                self.Status.OUTCOME_UNKNOWN: set(),
            }
            if self.status != previous.status and self.status not in allowed[previous.status]:
                raise ValidationError("Invalid communication delivery transition.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Communication delivery history cannot be deleted.")


__all__ = ["CommunicationDelivery"]
