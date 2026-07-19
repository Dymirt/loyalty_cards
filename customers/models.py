"""Customer-domain models and legacy customer compatibility aliases."""

from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

from dotykacka.models import Klient, Tenant


# ``Klient`` keeps its historical Django model label and database table.  New
# code uses the product-language alias while old imports remain valid.
Customer = Klient


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
    "CustomerExternalIdentity",
    "Klient",
]
