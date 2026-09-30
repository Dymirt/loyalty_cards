"""Customer-domain models and legacy customer compatibility aliases."""

import hashlib
import secrets

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from dotykacka.models import Klient, Tenant


# ``Klient`` keeps its historical Django model label and database table.  New
# code uses the product-language alias while old imports remain valid.
Customer = Klient


class CustomerExportApiToken(models.Model):
    """Revocable, tenant-scoped credential for exporting customer contacts."""

    TOKEN_PREFIX = "lst_live_"
    VISIBLE_PREFIX_LENGTH = 20

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.PROTECT,
        related_name="customer_export_api_tokens",
    )
    name = models.CharField(
        max_length=160,
        help_text=_("Nazwa klienta lub systemu korzystającego z API."),
    )
    token_prefix = models.CharField(max_length=20, unique=True, editable=False)
    token_hash = models.CharField(max_length=64, unique=True, editable=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_customer_export_api_tokens",
        blank=True,
        null=True,
        editable=False,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(blank=True, null=True, editable=False)
    revoked_at = models.DateTimeField(blank=True, null=True, editable=False)

    class Meta:
        ordering = ("-created_at", "-pk")
        verbose_name = _("token API eksportu klientów")
        verbose_name_plural = _("tokeny API eksportu klientów")

    def __str__(self):
        return f"{self.tenant}: {self.name} ({self.token_prefix}…)"

    @property
    def is_active(self):
        return self.revoked_at is None and self.tenant.is_active

    @staticmethod
    def digest(raw_token):
        return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()

    @classmethod
    def generate_credentials(cls):
        raw_token = f"{cls.TOKEN_PREFIX}{secrets.token_urlsafe(32)}"
        return (
            raw_token,
            raw_token[: cls.VISIBLE_PREFIX_LENGTH],
            cls.digest(raw_token),
        )

    @classmethod
    def issue(cls, *, tenant, name, created_by=None):
        raw_token, token_prefix, token_hash = cls.generate_credentials()
        token = cls.objects.create(
            tenant=tenant,
            name=name,
            token_prefix=token_prefix,
            token_hash=token_hash,
            created_by=created_by,
        )
        return token, raw_token

    def revoke(self):
        if self.revoked_at is None:
            self.revoked_at = timezone.now()
            self.save(update_fields=("revoked_at",))


class CustomerExternalIdentity(models.Model):
    """Stable mapping between a local customer and one external provider."""

    class SyncStatus(models.TextChoices):
        PENDING = "pending", _("Oczekuje")
        SYNCED = "synced", _("Zsynchronizowano")
        FAILED = "failed", _("Błąd")
        DISABLED = "disabled", _("Wyłączona")

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.PROTECT,
        related_name="customer_external_identities",
    )
    customer = models.ForeignKey(
        Klient,
        on_delete=models.PROTECT,
        related_name="external_identities",
    )
    provider = models.CharField(max_length=40)
    remote_id = models.CharField(max_length=240, blank=True, null=True)
    remote_version = models.CharField(max_length=240, blank=True)
    sync_status = models.CharField(
        max_length=16,
        choices=SyncStatus.choices,
        default=SyncStatus.PENDING,
        db_index=True,
    )
    last_attempted_at = models.DateTimeField(blank=True, null=True)
    last_synced_at = models.DateTimeField(blank=True, null=True)
    last_error_code = models.CharField(max_length=80, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("customer", "provider"),
                name="unique_customer_external_provider",
            ),
            models.UniqueConstraint(
                fields=("tenant", "provider", "remote_id"),
                name="unique_tenant_provider_remote_customer",
            ),
        ]
        ordering = ("provider", "customer_id")

    def clean(self):
        if self.customer_id and self.tenant_id != self.customer.tenant_id:
            raise ValidationError(
                {"customer": _("Klient i tożsamość zewnętrzna muszą należeć do tej samej firmy.")}
            )


class ConsentRecord(models.Model):
    """Append-only evidence of a customer's explicit consent decision."""

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.PROTECT,
        related_name="consent_records",
    )
    customer = models.ForeignKey(
        Klient,
        on_delete=models.PROTECT,
        related_name="consent_records",
    )
    purpose = models.CharField(max_length=80)
    policy_version = models.CharField(max_length=80)
    consent_text = models.TextField()
    consent_text_sha256 = models.CharField(max_length=64)
    granted = models.BooleanField()
    source = models.CharField(max_length=40, default="registration")
    recorded_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(blank=True, null=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ("-recorded_at", "-pk")

    def clean(self):
        if self.customer_id and self.tenant_id != self.customer.tenant_id:
            raise ValidationError(
                {"customer": _("Klient i zapis zgody muszą należeć do tej samej firmy.")}
            )

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError(_("Historii zgód nie można zmieniać; utwórz nowy zapis."))
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError(_("Historii zgód nie można usuwać."))


__all__ = [
    "ConsentRecord",
    "Customer",
    "CustomerExportApiToken",
    "CustomerExternalIdentity",
    "Klient",
]
