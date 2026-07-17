"""Artwork models plus aliases to legacy design/artifact table owners."""

from django.core.exceptions import ValidationError
from django.db import models

from dotykacka.models import (
    CardArtifact,
    CardDesign,
    PhysicalCard,
    Tenant,
    TenantBrandRevision,
)


class CropPlan(models.Model):
    """Exact immutable crop coordinates used for one design/card render."""

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.PROTECT,
        related_name="crop_plans",
    )
    design = models.ForeignKey(
        CardDesign,
        on_delete=models.PROTECT,
        related_name="crop_plans",
    )
    physical_card = models.ForeignKey(
        PhysicalCard,
        on_delete=models.PROTECT,
        related_name="crop_plans",
        blank=True,
        null=True,
    )
    card_code = models.CharField(max_length=60)
    seed = models.CharField(max_length=64)
    source_sha256 = models.CharField(max_length=64)
    source_width = models.PositiveIntegerField()
    source_height = models.PositiveIntegerField()
    resized_width = models.PositiveIntegerField()
    resized_height = models.PositiveIntegerField()
    crop_left = models.PositiveIntegerField()
    crop_top = models.PositiveIntegerField()
    crop_right = models.PositiveIntegerField()
    crop_bottom = models.PositiveIntegerField()
    render_version = models.CharField(max_length=40, default="card-artwork-v1")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("design", "card_code", "render_version"),
                name="unique_design_card_crop_plan",
            )
        ]
        ordering = ("design_id", "card_code")

    @property
    def crop_box(self):
        return (
            self.crop_left,
            self.crop_top,
            self.crop_right,
            self.crop_bottom,
        )

    def clean(self):
        errors = {}
        if self.design_id and self.design.tenant_id != self.tenant_id:
            errors["design"] = "Design and crop plan must share a tenant."
        if self.physical_card_id:
            if self.physical_card.tenant_id != self.tenant_id:
                errors["physical_card"] = "Card and crop plan must share a tenant."
            if self.physical_card.code != self.card_code:
                errors["card_code"] = "Crop-plan code must match its physical card."
        if self.crop_right <= self.crop_left or self.crop_bottom <= self.crop_top:
            errors["crop_right"] = "Crop coordinates must describe a positive rectangle."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("Crop plans are immutable; create a new render version.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Crop plans cannot be deleted.")


__all__ = [
    "CardArtifact",
    "CardDesign",
    "CropPlan",
    "TenantBrandRevision",
]
