"""Centralized print-request, production-package, and fulfillment records."""

from uuid import uuid4

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class AppendOnlyMixin:
    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError(_("Historia druku jest tylko do dopisywania."))
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError(_("Historii druku nie można usuwać."))


class PrintRequest(models.Model):
    class Status(models.TextChoices):
        SUBMITTED = "submitted", _("Złożone")
        APPROVED = "approved", _("Zatwierdzone")
        REJECTED = "rejected", _("Odrzucone")
        ALLOCATED = "allocated", _("Przydzielono karty")
        GENERATING = "generating", _("Generowanie")
        READY = "ready", _("Gotowe")
        FAILED = "failed", _("Błąd")
        PRINTING = "printing", _("W druku")
        PRINTED = "printed", _("Wydrukowane")
        PACKED = "packed", _("Spakowane")
        DISPATCHED = "dispatched", _("Wysłane")
        DELIVERED = "delivered", _("Dostarczone")
        CANCELLED = "cancelled", _("Anulowane")

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
                errors[name] = _("Wybrany zapis musi należeć do firmy składającej zamówienie.")
        if self.proof_front_id and self.proof_front.design_id != self.design_id:
            errors["proof_front"] = _("Próbka przodu musi należeć do wybranego projektu.")
        if self.proof_back_id and self.proof_back.design_id != self.design_id:
            errors["proof_back"] = _("Próbka tyłu musi należeć do wybranego projektu.")
        if self.quote_id and self.quote.quantity != self.quantity:
            errors["quantity"] = _("Liczba kart musi odpowiadać zaakceptowanej kalkulacji.")
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
                raise ValidationError(_("Szczegółów złożonego zamówienia druku nie można zmieniać."))
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError(_("Zamówień druku nie można usuwać."))


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
        ALLOCATED = "allocated", _("Przydzielono karty")
        GENERATING = "generating", _("Generowanie")
        READY = "ready", _("Gotowy")
        FAILED = "failed", _("Błąd")
        CANCELLED = "cancelled", _("Anulowany")

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
            errors["print_request"] = _("Seria druku i zamówienie muszą należeć do tej samej firmy.")
        if self.design_id and self.design.tenant_id != self.tenant_id:
            errors["design"] = _("Seria druku i projekt muszą należeć do tej samej firmy.")
        if self.quote_id and self.quote.tenant_id != self.tenant_id:
            errors["quote"] = _("Seria druku i kalkulacja muszą należeć do tej samej firmy.")
        if self.batch_id and self.batch.tenant_id != self.tenant_id:
            errors["batch"] = _("Seria druku i partia muszą należeć do tej samej firmy.")
        if self.quantity and self.end_number - self.start_number + 1 != self.quantity:
            errors["quantity"] = _("Liczba kart w serii musi odpowiadać przydzielonemu zakresowi.")
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
                raise ValidationError(_("Danych przydzielonej serii druku nie można zmieniać."))
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError(_("Serii druku nie można usuwać."))


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
            errors["physical_card"] = _("Przydzielona karta musi należeć do firmy przypisanej do serii.")
        if self.physical_card_id and self.physical_card.code != self.code_snapshot:
            errors["code_snapshot"] = _("Zapisany kod musi odpowiadać przydzielonej karcie.")
        if self.crop_plan_id and (
            self.crop_plan.tenant_id != self.print_run.tenant_id
            or self.crop_plan.design_id != self.print_run.design_id
            or self.crop_plan.card_code != self.code_snapshot
            or self.crop_plan.physical_card_id not in (None, self.physical_card_id)
        ):
            errors["crop_plan"] = _("Plan kadrowania musi odpowiadać kodowi karty i projektowi.")
        for name in ("front_artifact", "back_artifact", "barcode_artifact"):
            artifact = getattr(self, name, None)
            if artifact is not None and artifact.physical_card_id != self.physical_card_id:
                errors[name] = _("Plik produkcyjny musi należeć do przydzielonej karty.")
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.pk:
            previous = type(self).objects.get(pk=self.pk)
            for field in ("print_run_id", "physical_card_id", "position", "code_snapshot"):
                if getattr(previous, field) != getattr(self, field):
                    raise ValidationError(_("Przydział serii druku jest niezmienny."))
            for field in (
                "crop_plan_id",
                "front_artifact_id",
                "back_artifact_id",
                "barcode_artifact_id",
            ):
                old, new = getattr(previous, field), getattr(self, field)
                if old and old != new:
                    raise ValidationError(_("Powiązań śledzenia produkcji nie można zastępować."))
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError(_("Kart przydzielonych do serii druku nie można usuwać."))


class PrintJob(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", _("Oczekuje")
        RUNNING = "running", _("W toku")
        RETRY = "retry", _("Zaplanowano ponowienie")
        SUCCEEDED = "succeeded", _("Zakończono")
        FAILED = "failed", _("Błąd")
        CANCELLED = "cancelled", _("Anulowano")

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
        raise ValidationError(_("Historii zadań druku nie można usuwać."))


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
        PRINTING = "printing", _("Rozpoczęto druk")
        PRINTED = "printed", _("Wydrukowano")
        PACKED = "packed", _("Spakowano")
        DISPATCHED = "dispatched", _("Wysłano")
        DELIVERED = "delivered", _("Dostarczono")
        CORRECTION = "correction", _("Korekta")

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
                errors[name] = _("Zakres realizacji musi należeć do firmy przypisanej do zdarzenia.")
        if self.event_type == self.Kind.CORRECTION:
            if not self.compensates_id:
                errors["compensates"] = _("Korekta musi wskazywać korygowane zdarzenie.")
            if not self.reason.strip():
                errors["reason"] = _("Podaj powód korekty.")
        elif self.compensates_id:
            errors["compensates"] = _("Tylko zdarzenie korekty może korygować historię.")
        if self.compensates_id and self.compensates.tenant_id != self.tenant_id:
            errors["compensates"] = _("Korekta i pierwotne zdarzenie muszą należeć do tej samej firmy.")
        if not any((self.print_request_id, self.print_run_id, self.physical_card_id)):
            errors["print_request"] = _("Realizacja wymaga wskazania zamówienia, serii lub karty.")
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
