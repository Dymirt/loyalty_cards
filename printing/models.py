"""Centralized print-request, production-package, and fulfillment records."""

from uuid import uuid4

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone


class AppendOnlyMixin:
    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("Historical printing records are append-only.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Historical printing records cannot be deleted.")


class PrintRequest(models.Model):
    class Status(models.TextChoices):
        SUBMITTED = "submitted", "Submitted"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        ALLOCATED = "allocated", "Allocated"
        GENERATING = "generating", "Generating"
        READY = "ready", "Ready"
        FAILED = "failed", "Failed"
        PRINTING = "printing", "Printing"
        PRINTED = "printed", "Printed"
        PACKED = "packed", "Packed"
        DISPATCHED = "dispatched", "Dispatched"
        DELIVERED = "delivered", "Delivered"
        CANCELLED = "cancelled", "Cancelled"

    tenant = models.ForeignKey(
        "dotykacka.Tenant",
        on_delete=models.PROTECT,
        related_name="print_requests",
    )
    design = models.ForeignKey(
        "dotykacka.CardDesign",
        on_delete=models.PROTECT,
        related_name="print_requests",
    )
    proof_front = models.ForeignKey(
        "dotykacka.CardArtifact",
        on_delete=models.PROTECT,
        related_name="print_requests_as_front_proof",
    )
    proof_back = models.ForeignKey(
        "dotykacka.CardArtifact",
        on_delete=models.PROTECT,
        related_name="print_requests_as_back_proof",
    )
    quote = models.OneToOneField(
        "billing.Quote",
        on_delete=models.PROTECT,
        related_name="print_request",
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="submitted_print_requests",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.SUBMITTED,
        db_index=True,
    )
    idempotency_key = models.CharField(max_length=180)
    quantity = models.PositiveIntegerField()
    proof_checksum = models.CharField(max_length=64)
    delivery_name = models.CharField(max_length=160)
    delivery_address_line1 = models.CharField(max_length=240)
    delivery_address_line2 = models.CharField(max_length=240, blank=True)
    delivery_postal_code = models.CharField(max_length=24)
    delivery_city = models.CharField(max_length=120)
    delivery_country = models.CharField(max_length=2, default="PL")
    notes = models.TextField(blank=True)
    snapshot = models.JSONField(default=dict)
    submitted_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("tenant", "idempotency_key"),
                name="printing_unique_tenant_request_key",
            ),
            models.CheckConstraint(
                condition=Q(quantity__gt=0),
                name="printing_request_quantity_positive",
            ),
        ]
        ordering = ("-submitted_at", "-pk")

    def clean(self):
        errors = {}
        for name in ("design", "proof_front", "proof_back", "quote"):
            value = getattr(self, name, None)
            if value is not None and value.tenant_id != self.tenant_id:
                errors[name] = "The selected record must belong to the request tenant."
        if self.proof_front_id and self.proof_front.design_id != self.design_id:
            errors["proof_front"] = "Front proof must belong to the selected design."
        if self.proof_back_id and self.proof_back.design_id != self.design_id:
            errors["proof_back"] = "Back proof must belong to the selected design."
        if self.quote_id and self.quote.quantity != self.quantity:
            errors["quantity"] = "Request quantity must match the accepted quote."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.delivery_country = (self.delivery_country or "").upper()
        if self.pk:
            previous = type(self).objects.get(pk=self.pk)
            immutable = (
                "tenant_id",
                "design_id",
                "proof_front_id",
                "proof_back_id",
                "quote_id",
                "requested_by_id",
                "idempotency_key",
                "quantity",
                "proof_checksum",
                "delivery_name",
                "delivery_address_line1",
                "delivery_address_line2",
                "delivery_postal_code",
                "delivery_city",
                "delivery_country",
                "notes",
                "snapshot",
            )
            if any(getattr(previous, field) != getattr(self, field) for field in immutable):
                raise ValidationError("Submitted print-request details are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Print requests cannot be deleted.")


class PrintRequestEvent(AppendOnlyMixin, models.Model):
    print_request = models.ForeignKey(
        PrintRequest,
        on_delete=models.PROTECT,
        related_name="status_events",
    )
    from_status = models.CharField(max_length=20, blank=True)
    to_status = models.CharField(max_length=20, choices=PrintRequest.Status.choices)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="print_request_events",
        blank=True,
        null=True,
    )
    reason = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("created_at", "pk")


class PrintRun(models.Model):
    class Status(models.TextChoices):
        ALLOCATED = "allocated", "Allocated"
        GENERATING = "generating", "Generating"
        READY = "ready", "Ready"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"

    print_request = models.OneToOneField(
        PrintRequest,
        on_delete=models.PROTECT,
        related_name="print_run",
    )
    tenant = models.ForeignKey(
        "dotykacka.Tenant",
        on_delete=models.PROTECT,
        related_name="print_runs",
    )
    design = models.ForeignKey(
        "dotykacka.CardDesign",
        on_delete=models.PROTECT,
        related_name="print_runs",
    )
    quote = models.OneToOneField(
        "billing.Quote",
        on_delete=models.PROTECT,
        related_name="print_run",
    )
    batch = models.OneToOneField(
        "dotykacka.CardBatch",
        on_delete=models.PROTECT,
        related_name="print_run",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_print_runs",
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.ALLOCATED,
        db_index=True,
    )
    quantity = models.PositiveIntegerField()
    start_number = models.PositiveIntegerField()
    end_number = models.PositiveIntegerField()
    layout_snapshot = models.JSONField(default=dict)
    design_snapshot = models.JSONField(default=dict)
    quote_snapshot = models.JSONField(default=dict)
    started_at = models.DateTimeField(blank=True, null=True)
    validated_at = models.DateTimeField(blank=True, null=True)
    completed_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(quantity__gt=0),
                name="printing_run_quantity_positive",
            ),
            models.CheckConstraint(
                condition=Q(end_number__gte=models.F("start_number")),
                name="printing_run_number_range_valid",
            ),
        ]
        ordering = ("-created_at", "-pk")

    def clean(self):
        errors = {}
        if self.print_request_id and self.print_request.tenant_id != self.tenant_id:
            errors["print_request"] = "Run and request must share a tenant."
        if self.design_id and self.design.tenant_id != self.tenant_id:
            errors["design"] = "Run and design must share a tenant."
        if self.quote_id and self.quote.tenant_id != self.tenant_id:
            errors["quote"] = "Run and quote must share a tenant."
        if self.batch_id and self.batch.tenant_id != self.tenant_id:
            errors["batch"] = "Run and batch must share a tenant."
        if self.quantity and self.end_number - self.start_number + 1 != self.quantity:
            errors["quantity"] = "Run quantity must match the allocated number range."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.pk:
            previous = type(self).objects.get(pk=self.pk)
            immutable = (
                "print_request_id",
                "tenant_id",
                "design_id",
                "quote_id",
                "batch_id",
                "created_by_id",
                "quantity",
                "start_number",
                "end_number",
                "layout_snapshot",
                "design_snapshot",
                "quote_snapshot",
            )
            if any(getattr(previous, field) != getattr(self, field) for field in immutable):
                raise ValidationError("Allocated print-run inputs are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Print runs cannot be deleted.")


class PrintRunCard(models.Model):
    print_run = models.ForeignKey(
        PrintRun,
        on_delete=models.PROTECT,
        related_name="run_cards",
    )
    physical_card = models.OneToOneField(
        "dotykacka.PhysicalCard",
        on_delete=models.PROTECT,
        related_name="production_allocation",
    )
    position = models.PositiveIntegerField()
    code_snapshot = models.CharField(max_length=60)
    crop_plan = models.ForeignKey(
        "card_artwork.CropPlan",
        on_delete=models.PROTECT,
        related_name="print_run_cards",
        blank=True,
        null=True,
    )
    front_artifact = models.ForeignKey(
        "dotykacka.CardArtifact",
        on_delete=models.PROTECT,
        related_name="print_run_cards_as_front",
        blank=True,
        null=True,
    )
    back_artifact = models.ForeignKey(
        "dotykacka.CardArtifact",
        on_delete=models.PROTECT,
        related_name="print_run_cards_as_back",
        blank=True,
        null=True,
    )
    barcode_artifact = models.ForeignKey(
        "dotykacka.CardArtifact",
        on_delete=models.PROTECT,
        related_name="print_run_cards_as_barcode",
        blank=True,
        null=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("print_run", "position"),
                name="printing_unique_run_card_position",
            ),
            models.CheckConstraint(
                condition=Q(position__gt=0),
                name="printing_run_card_position_positive",
            ),
        ]
        ordering = ("position",)

    def clean(self):
        errors = {}
        if self.physical_card_id and self.physical_card.tenant_id != self.print_run.tenant_id:
            errors["physical_card"] = "Allocated card must belong to the run tenant."
        if self.physical_card_id and self.physical_card.code != self.code_snapshot:
            errors["code_snapshot"] = "Code snapshot must match the allocated card."
        if self.crop_plan_id and (
            self.crop_plan.tenant_id != self.print_run.tenant_id
            or self.crop_plan.design_id != self.print_run.design_id
            or self.crop_plan.card_code != self.code_snapshot
            or self.crop_plan.physical_card_id not in (None, self.physical_card_id)
        ):
            errors["crop_plan"] = "Crop plan must match the allocated card code and design."
        for name in ("front_artifact", "back_artifact", "barcode_artifact"):
            artifact = getattr(self, name, None)
            if artifact is not None and artifact.physical_card_id != self.physical_card_id:
                errors[name] = "Production artifact must belong to the allocated card."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.pk:
            previous = type(self).objects.get(pk=self.pk)
            for field in ("print_run_id", "physical_card_id", "position", "code_snapshot"):
                if getattr(previous, field) != getattr(self, field):
                    raise ValidationError("Print-run allocation is immutable.")
            for field in (
                "crop_plan_id",
                "front_artifact_id",
                "back_artifact_id",
                "barcode_artifact_id",
            ):
                old, new = getattr(previous, field), getattr(self, field)
                if old and old != new:
                    raise ValidationError("Production trace links cannot be replaced.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Allocated print-run cards cannot be deleted.")


class PrintJob(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        RETRY = "retry", "Retry scheduled"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"

    print_run = models.ForeignKey(
        PrintRun,
        on_delete=models.PROTECT,
        related_name="jobs",
    )
    idempotency_key = models.CharField(max_length=180, unique=True)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    attempts = models.PositiveSmallIntegerField(default=0)
    max_attempts = models.PositiveSmallIntegerField(default=3)
    available_at = models.DateTimeField(default=timezone.now, db_index=True)
    locked_at = models.DateTimeField(blank=True, null=True)
    locked_by = models.CharField(max_length=120, blank=True)
    finished_at = models.DateTimeField(blank=True, null=True)
    last_error_code = models.CharField(max_length=80, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(
                fields=("status", "available_at", "created_at"),
                name="printing_job_claim_idx",
            )
        ]
        ordering = ("created_at", "pk")

    def delete(self, *args, **kwargs):
        raise ValidationError("Print-job history cannot be deleted.")


class PrintPackage(AppendOnlyMixin, models.Model):
    print_run = models.OneToOneField(
        PrintRun,
        on_delete=models.PROTECT,
        related_name="package",
    )
    storage_key = models.UUIDField(default=uuid4, unique=True, editable=False)
    storage_path = models.CharField(max_length=700)
    sha256 = models.CharField(max_length=64)
    size_bytes = models.PositiveBigIntegerField()
    manifest = models.JSONField(default=dict)
    validated_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)


class FulfillmentEvent(AppendOnlyMixin, models.Model):
    class Kind(models.TextChoices):
        PRINTING = "printing", "Printing started"
        PRINTED = "printed", "Printed"
        PACKED = "packed", "Packed"
        DISPATCHED = "dispatched", "Dispatched"
        DELIVERED = "delivered", "Delivered"
        CORRECTION = "correction", "Correction"

    tenant = models.ForeignKey(
        "dotykacka.Tenant",
        on_delete=models.PROTECT,
        related_name="fulfillment_events",
    )
    print_request = models.ForeignKey(
        PrintRequest,
        on_delete=models.PROTECT,
        related_name="fulfillment_events",
        blank=True,
        null=True,
    )
    print_run = models.ForeignKey(
        PrintRun,
        on_delete=models.PROTECT,
        related_name="fulfillment_events",
        blank=True,
        null=True,
    )
    physical_card = models.ForeignKey(
        "dotykacka.PhysicalCard",
        on_delete=models.PROTECT,
        related_name="fulfillment_events",
        blank=True,
        null=True,
    )
    event_type = models.CharField(max_length=16, choices=Kind.choices, db_index=True)
    compensates = models.OneToOneField(
        "self",
        on_delete=models.PROTECT,
        related_name="correction_event",
        blank=True,
        null=True,
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="fulfillment_events",
    )
    idempotency_key = models.CharField(max_length=220)
    occurred_at = models.DateTimeField(default=timezone.now)
    reference = models.CharField(max_length=160, blank=True)
    notes = models.TextField(blank=True)
    reason = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("tenant", "idempotency_key"),
                name="printing_unique_tenant_fulfillment_key",
            )
        ]
        ordering = ("occurred_at", "pk")

    def clean(self):
        errors = {}
        for name in ("print_request", "print_run", "physical_card"):
            value = getattr(self, name, None)
            if value is not None and value.tenant_id != self.tenant_id:
                errors[name] = "Fulfillment scope must belong to the event tenant."
        if self.event_type == self.Kind.CORRECTION:
            if not self.compensates_id:
                errors["compensates"] = "A correction must reference the event it compensates."
            if not self.reason.strip():
                errors["reason"] = "A correction reason is required."
        elif self.compensates_id:
            errors["compensates"] = "Only correction events can compensate history."
        if self.compensates_id and self.compensates.tenant_id != self.tenant_id:
            errors["compensates"] = "Correction and original event must share a tenant."
        if not any((self.print_request_id, self.print_run_id, self.physical_card_id)):
            errors["print_request"] = "Fulfillment requires request, run, or card scope."
        if errors:
            raise ValidationError(errors)


__all__ = [
    "FulfillmentEvent",
    "PrintJob",
    "PrintPackage",
    "PrintRequest",
    "PrintRequestEvent",
    "PrintRun",
    "PrintRunCard",
]
