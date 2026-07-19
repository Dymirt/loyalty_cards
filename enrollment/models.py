"""Immutable local enrollment, access-link, and follow-up trace records."""

from uuid import uuid4

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q


class AppendOnlyMixin:
    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("Enrollment history is append-only.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Enrollment history cannot be deleted.")


class Enrollment(AppendOnlyMixin, models.Model):
    """One committed local customer/card/consent registration."""

    tenant = models.ForeignKey(
        "dotykacka.Tenant",
        on_delete=models.PROTECT,
        related_name="enrollments",
    )
    customer = models.OneToOneField(
        "dotykacka.Klient",
        on_delete=models.PROTECT,
        related_name="enrollment",
    )
    physical_card = models.OneToOneField(
        "dotykacka.PhysicalCard",
        on_delete=models.PROTECT,
        related_name="enrollment",
    )
    consent_record = models.OneToOneField(
        "customers.ConsentRecord",
        on_delete=models.PROTECT,
        related_name="enrollment",
    )
    usage_event = models.OneToOneField(
        "billing.UsageEvent",
        on_delete=models.PROTECT,
        related_name="enrollment",
        blank=True,
        null=True,
    )
    brand_revision = models.ForeignKey(
        "dotykacka.TenantBrandRevision",
        on_delete=models.PROTECT,
        related_name="enrollments",
        blank=True,
        null=True,
    )
    card_design = models.ForeignKey(
        "dotykacka.CardDesign",
        on_delete=models.PROTECT,
        related_name="enrollments",
        blank=True,
        null=True,
    )
    registration_key = models.CharField(max_length=180)
    source = models.CharField(max_length=40, default="public_registration")
    brand_snapshot = models.JSONField(default=dict)
    consent_snapshot = models.JSONField(default=dict)
    registered_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("tenant", "registration_key"),
                name="enrollment_unique_tenant_registration_key",
            )
        ]
        ordering = ("-registered_at", "-pk")

    def clean(self):
        errors = {}
        for name in ("customer", "physical_card", "consent_record"):
            value = getattr(self, name, None)
            if value is not None and value.tenant_id != self.tenant_id:
                errors[name] = "Enrollment records must belong to one tenant."
        if self.usage_event_id and self.usage_event.tenant_id != self.tenant_id:
            errors["usage_event"] = "Usage and enrollment must share a tenant."
        if self.brand_revision_id and self.brand_revision.tenant_id != self.tenant_id:
            errors["brand_revision"] = "Brand revision and enrollment must share a tenant."
        if self.card_design_id and self.card_design.tenant_id != self.tenant_id:
            errors["card_design"] = "Card design and enrollment must share a tenant."
        if self.customer_id and self.physical_card_id:
            if self.physical_card.customer_id != self.customer_id:
                errors["physical_card"] = "The card must be assigned to the enrollment customer."
        if errors:
            raise ValidationError(errors)


class EnrollmentAccessLink(AppendOnlyMixin, models.Model):
    class Purpose(models.TextChoices):
        WALLET_STATUS = "wallet_status", "Wallet and follow-up status"

    class Reason(models.TextChoices):
        REGISTRATION = "registration", "Registration"
        RESEND = "resend", "Explicit resend"

    enrollment = models.ForeignKey(
        Enrollment,
        on_delete=models.PROTECT,
        related_name="access_links",
    )
    public_id = models.UUIDField(default=uuid4, unique=True, editable=False)
    purpose = models.CharField(
        max_length=32,
        choices=Purpose.choices,
        default=Purpose.WALLET_STATUS,
    )
    reason = models.CharField(max_length=20, choices=Reason.choices)
    expires_at = models.DateTimeField(db_index=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_enrollment_access_links",
        blank=True,
        null=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at", "-pk")


class EnrollmentFollowUp(AppendOnlyMixin, models.Model):
    class Operation(models.TextChoices):
        INITIAL = "initial", "Initial enrollment"
        RESEND = "resend", "Explicit resend"

    enrollment = models.ForeignKey(
        Enrollment,
        on_delete=models.PROTECT,
        related_name="followups",
    )
    integration_job = models.OneToOneField(
        "integrations.IntegrationJob",
        on_delete=models.PROTECT,
        related_name="enrollment_followup",
    )
    kind = models.CharField(max_length=100)
    generation = models.PositiveIntegerField(default=1)
    operation = models.CharField(max_length=16, choices=Operation.choices)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="requested_enrollment_followups",
        blank=True,
        null=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("enrollment", "kind", "generation"),
                name="enrollment_unique_followup_generation",
            ),
            models.CheckConstraint(
                condition=Q(generation__gt=0),
                name="enrollment_followup_generation_positive",
            ),
        ]
        ordering = ("created_at", "pk")

    def clean(self):
        if (
            self.integration_job_id
            and self.enrollment_id
            and self.integration_job.tenant_id != self.enrollment.tenant_id
        ):
            raise ValidationError(
                {"integration_job": "Follow-up job and enrollment must share a tenant."}
            )
        if self.integration_job_id and self.kind != self.integration_job.kind:
            raise ValidationError({"kind": "Follow-up kind must match its job kind."})


class EnrollmentEvent(AppendOnlyMixin, models.Model):
    class Kind(models.TextChoices):
        REGISTERED = "registered", "Registered"
        CARD_ASSIGNED = "card_assigned", "Card assigned"
        CONSENT_RECORDED = "consent_recorded", "Consent recorded"
        ISSUANCE_RECORDED = "issuance_recorded", "Issuance recorded"
        FOLLOWUPS_ENQUEUED = "followups_enqueued", "Follow-ups enqueued"
        RETRY_REQUESTED = "retry_requested", "Retry requested"
        RESEND_REQUESTED = "resend_requested", "Resend requested"

    enrollment = models.ForeignKey(
        Enrollment,
        on_delete=models.PROTECT,
        related_name="events",
    )
    kind = models.CharField(max_length=32, choices=Kind.choices)
    idempotency_key = models.CharField(max_length=180)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="enrollment_events",
        blank=True,
        null=True,
    )
    integration_job = models.ForeignKey(
        "integrations.IntegrationJob",
        on_delete=models.PROTECT,
        related_name="enrollment_events",
        blank=True,
        null=True,
    )
    reason = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("enrollment", "idempotency_key"),
                name="enrollment_unique_event_key",
            )
        ]
        ordering = ("created_at", "pk")

    def clean(self):
        if (
            self.integration_job_id
            and self.enrollment_id
            and self.integration_job.tenant_id != self.enrollment.tenant_id
        ):
            raise ValidationError(
                {"integration_job": "Event job and enrollment must share a tenant."}
            )


__all__ = [
    "Enrollment",
    "EnrollmentAccessLink",
    "EnrollmentEvent",
    "EnrollmentFollowUp",
]
