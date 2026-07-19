"""Tenant-domain models and historical compatibility imports.

The legacy ``dotykacka`` app retains Django state and database-table ownership
during Phase 5.  These aliases give new code an owning-domain import path
without registering a second model or touching stored data.
"""

import re

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

from dotykacka.models import (
    Tenant,
    TenantBrand,
    TenantBrandRevision,
    TenantMembership,
)


class TenantDomain(models.Model):
    """A requested or platform-verified hostname for public enrollment."""

    class Status(models.TextChoices):
        PENDING = "pending", _("Oczekuje na weryfikację")
        VERIFIED = "verified", _("Zweryfikowana")
        DISABLED = "disabled", _("Wyłączona")

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.PROTECT,
        related_name="registration_domains",
    )
    primary_for_tenant = models.OneToOneField(
        Tenant,
        on_delete=models.PROTECT,
        related_name="primary_registration_domain",
        blank=True,
        null=True,
        editable=False,
    )
    hostname = models.CharField(max_length=253, unique=True)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    is_primary = models.BooleanField(default=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="requested_tenant_domains",
        blank=True,
        null=True,
    )
    verified_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("tenant_id", "-is_primary", "hostname")
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(is_primary=False, primary_for_tenant__isnull=True)
                    | models.Q(is_primary=True, primary_for_tenant=models.F("tenant"))
                ),
                name="tenant_domain_primary_marker_matches",
            )
        ]

    def clean(self):
        self.hostname = (self.hostname or "").strip().lower().rstrip(".")
        if not re.fullmatch(
            r"(?=.{1,253}\Z)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
            r"[a-z]{2,63}",
            self.hostname,
        ):
            raise ValidationError(
                {
                    "hostname": _(
                        "Podaj nazwę hosta, na przykład club.example.com, bez schematu i ścieżki."
                    )
                }
            )
        if self.status == self.Status.VERIFIED and self.verified_at is None:
            raise ValidationError(
                {"verified_at": _("Zweryfikowana domena wymaga daty weryfikacji.")}
            )
        if self.is_primary and self.status != self.Status.VERIFIED:
            raise ValidationError(
                {"is_primary": _("Domeną główną może być tylko domena zweryfikowana.")}
            )
        self.primary_for_tenant_id = self.tenant_id if self.is_primary else None

    def save(self, *args, **kwargs):
        self.hostname = (self.hostname or "").strip().lower().rstrip(".")
        self.primary_for_tenant_id = self.tenant_id if self.is_primary else None
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError(_("Historii domen firmy nie można usuwać; wyłącz domenę."))


__all__ = [
    "Tenant",
    "TenantBrand",
    "TenantBrandRevision",
    "TenantDomain",
    "TenantMembership",
]
