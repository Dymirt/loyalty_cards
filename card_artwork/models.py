"""Artwork models plus aliases to legacy design/artifact table owners."""

from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

from dotykacka.models import (
    CardArtifact,
    CardDesign,
    PhysicalCard,
    Tenant,
    TenantBrandRevision,
)


class CardArtworkSource(models.Model):
    """Immutable tenant-owned master image available to card designs."""

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.PROTECT,
        related_name="card_artwork_sources",
    )
    name = models.CharField(max_length=160)
    image = models.ImageField(max_length=500)
    source_sha256 = models.CharField(max_length=64, blank=True)
    width_px = models.PositiveIntegerField(blank=True, null=True)
    height_px = models.PositiveIntegerField(blank=True, null=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_card_artwork_sources",
        blank=True,
        null=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("created_at", "id")

    def __str__(self):
        return self.name or Path(self.image.name).name

    def clean(self):
        if not self.image:
            raise ValidationError({"image": _("Obraz źródłowy jest wymagany.")})

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError(
                _("Obrazu źródłowego nie można nadpisać; dodaj nowy obraz.")
            )
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError(
            _("Obrazów źródłowych używanych przez projekty nie można usuwać.")
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
            errors["design"] = _("Projekt i plan kadrowania muszą należeć do tej samej firmy.")
        if self.physical_card_id:
            if self.physical_card.tenant_id != self.tenant_id:
                errors["physical_card"] = _("Karta i plan kadrowania muszą należeć do tej samej firmy.")
            if self.physical_card.code != self.card_code:
                errors["card_code"] = _("Kod planu kadrowania musi odpowiadać karcie fizycznej.")
        if self.crop_right <= self.crop_left or self.crop_bottom <= self.crop_top:
            errors["crop_right"] = _("Współrzędne kadrowania muszą wyznaczać poprawny prostokąt.")
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError(_("Planów kadrowania nie można zmieniać; utwórz nową wersję renderowania."))
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError(_("Planów kadrowania nie można usuwać."))


__all__ = [
    "CardArtifact",
    "CardArtworkSource",
    "CardDesign",
    "CropPlan",
    "TenantBrandRevision",
]
