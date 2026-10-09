"""Tenant-owned campaigns and durable communication-delivery evidence."""

from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _


def campaign_asset_path(instance, filename):
    extension = Path(filename).suffix.lower()
    if extension not in {".jpg", ".jpeg", ".png", ".webp"}:
        extension = ".bin"
    return (
        f"tenants/{instance.tenant.slug}/communications/"
        f"campaign-{instance.campaign_id}/{uuid4().hex}{extension}"
    )


class EmailCampaign(models.Model):
    """A tenant-scoped email draft and its immutable scheduled snapshot."""

    class Status(models.TextChoices):
        DRAFT = "draft", _("Szkic")
        SCHEDULED = "scheduled", _("Zaplanowana")
        SENDING = "sending", _("Wysyłanie")
        SENT = "sent", _("Wysłana")
        PARTIALLY_SENT = "partially_sent", _("Wysłana częściowo")
        CANCELLED = "cancelled", _("Anulowana")

    class GenerationSource(models.TextChoices):
        LOCAL = "local", _("Generator lokalny")
        OPENAI = "openai", "OpenAI"

    tenant = models.ForeignKey(
        "dotykacka.Tenant",
        on_delete=models.PROTECT,
        related_name="email_campaigns",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_email_campaigns",
    )
    name = models.CharField(max_length=160)
    goal = models.TextField()
    reference_links = models.JSONField(default=list, blank=True)
    subject = models.CharField(max_length=240, blank=True)
    preheader = models.CharField(max_length=240, blank=True)
    html_content = models.TextField(blank=True)
    text_content = models.TextField(blank=True)
    content_snapshot = models.JSONField(default=dict, blank=True)
    generation_source = models.CharField(
        max_length=16,
        choices=GenerationSource.choices,
        default=GenerationSource.LOCAL,
    )
    ai_model = models.CharField(max_length=120, blank=True)
    status = models.CharField(
        max_length=24,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
    )
    scheduled_for = models.DateTimeField(blank=True, null=True, db_index=True)
    recipient_count = models.PositiveIntegerField(default=0)
    sent_count = models.PositiveIntegerField(default=0)
    failed_count = models.PositiveIntegerField(default=0)
    sent_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at", "-pk")
        indexes = [
            models.Index(
                fields=("tenant", "status", "scheduled_for"),
                name="campaign_tenant_status_idx",
            )
        ]

    def __str__(self):
        return f"{self.tenant}: {self.name}"

    @property
    def is_editable(self):
        return self.status == self.Status.DRAFT

    def clean(self):
        errors = {}
        if self.status != self.Status.DRAFT and not self.scheduled_for:
            errors["scheduled_for"] = _("Zaplanowana kampania wymaga terminu wysyłki.")
        if self.sent_count + self.failed_count > self.recipient_count:
            errors["recipient_count"] = _("Liczniki wysyłki są niespójne.")
        if errors:
            raise ValidationError(errors)


class CampaignAsset(models.Model):
    """An uploaded visual reference owned by one tenant and one campaign."""

    tenant = models.ForeignKey(
        "dotykacka.Tenant",
        on_delete=models.PROTECT,
        related_name="campaign_assets",
    )
    campaign = models.ForeignKey(
        EmailCampaign,
        on_delete=models.PROTECT,
        related_name="assets",
    )
    image = models.ImageField(upload_to=campaign_asset_path, max_length=500)
    original_name = models.CharField(max_length=240)
    content_type = models.CharField(max_length=80, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="uploaded_campaign_assets",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("created_at", "pk")

    def clean(self):
        if self.campaign_id and self.campaign.tenant_id != self.tenant_id:
            raise ValidationError(
                {"campaign": _("Materiał i kampania muszą należeć do tej samej firmy.")}
            )

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError(_("Materiału kampanii nie można nadpisać; dodaj nowy plik."))
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError(_("Materiałów użytych w kampanii nie można usuwać."))


class CampaignRecipient(models.Model):
    """A recipient snapshot created when a campaign is scheduled."""

    class Status(models.TextChoices):
        PENDING = "pending", _("Oczekuje")
        SENDING = "sending", _("Wysyłanie")
        SENT = "sent", _("Wysłano")
        FAILED = "failed", _("Błąd")

    tenant = models.ForeignKey(
        "dotykacka.Tenant",
        on_delete=models.PROTECT,
        related_name="campaign_recipients",
    )
    campaign = models.ForeignKey(
        EmailCampaign,
        on_delete=models.PROTECT,
        related_name="recipients",
    )
    customer = models.ForeignKey(
        "dotykacka.Klient",
        on_delete=models.PROTECT,
        related_name="campaign_recipients",
    )
    integration_job = models.OneToOneField(
        "integrations.IntegrationJob",
        on_delete=models.PROTECT,
        related_name="campaign_recipient",
        blank=True,
        null=True,
    )
    email_snapshot = models.EmailField(max_length=254)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    error_code = models.CharField(max_length=80, blank=True)
    sent_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("campaign", "customer"),
                name="unique_campaign_customer_recipient",
            )
        ]
        ordering = ("created_at", "pk")

    def clean(self):
        errors = {}
        if self.campaign_id and self.campaign.tenant_id != self.tenant_id:
            errors["campaign"] = _("Kampania i odbiorca muszą należeć do tej samej firmy.")
        if self.customer_id and self.customer.tenant_id != self.tenant_id:
            errors["customer"] = _("Klient i odbiorca muszą należeć do tej samej firmy.")
        if self.integration_job_id and self.integration_job.tenant_id != self.tenant_id:
            errors["integration_job"] = _("Zadanie i odbiorca muszą należeć do tej samej firmy.")
        if errors:
            raise ValidationError(errors)


class CommunicationDelivery(models.Model):
    """One guarded email attempt; ambiguous outcomes are never auto-replayed."""

    class Channel(models.TextChoices):
        EMAIL = "email", _("E-mail")

    class Status(models.TextChoices):
        SENDING = "sending", _("Wysyłanie")
        SENT = "sent", _("Wysłano")
        OUTCOME_UNKNOWN = "outcome_unknown", _("Wynik nieznany")

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
            errors["customer"] = _("Klient i dostarczenie muszą należeć do tej samej firmy.")
        if self.integration_job_id and self.integration_job.tenant_id != self.tenant_id:
            errors["integration_job"] = _("Zadanie i dostarczenie muszą należeć do tej samej firmy.")
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
                raise ValidationError(_("Warunków dostarczenia wiadomości nie można zmieniać."))
            allowed = {
                self.Status.SENDING: {self.Status.SENT, self.Status.OUTCOME_UNKNOWN},
                self.Status.SENT: set(),
                self.Status.OUTCOME_UNKNOWN: set(),
            }
            if self.status != previous.status and self.status not in allowed[previous.status]:
                raise ValidationError(_("Niedozwolona zmiana stanu dostarczenia wiadomości."))
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError(_("Historii dostarczenia wiadomości nie można usuwać."))


__all__ = [
    "CampaignAsset",
    "CampaignRecipient",
    "CommunicationDelivery",
    "EmailCampaign",
]
