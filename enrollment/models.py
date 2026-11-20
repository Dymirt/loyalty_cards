"""Immutable physical and virtual enrollment trace records."""

import hashlib
import secrets
from uuid import uuid4

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _


class AppendOnlyMixin:
    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError(_("Historia rejestracji jest tylko do dopisywania."))
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError(_("Historii rejestracji nie można usuwać."))


class VirtualCardApiKey(models.Model):
    """Revocable tenant credential limited to virtual-card issuance."""

    TOKEN_PREFIX = "lvc_live_"
    VISIBLE_PREFIX_LENGTH = 20

    tenant = models.ForeignKey(
        "dotykacka.Tenant",
        on_delete=models.PROTECT,
        related_name="virtual_card_api_keys",
    )
    name = models.CharField(max_length=160)
    token_prefix = models.CharField(max_length=20, unique=True, editable=False)
    token_hash = models.CharField(max_length=64, unique=True, editable=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_virtual_card_api_keys",
        blank=True,
        null=True,
        editable=False,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(blank=True, null=True, editable=False)
    revoked_at = models.DateTimeField(blank=True, null=True, editable=False)

    class Meta:
        ordering = ("-created_at", "-pk")

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
        key = cls.objects.create(
            tenant=tenant,
            name=name,
            token_prefix=token_prefix,
            token_hash=token_hash,
            created_by=created_by,
        )
        return key, raw_token

    def revoke(self):
        if self.revoked_at is None:
            from django.utils import timezone

            self.revoked_at = timezone.now()
            self.save(update_fields=("revoked_at",))


class VirtualCardApplication(AppendOnlyMixin, models.Model):
    """One accepted request assigning a prepared MB-* visual to Wallet cards."""

    class Source(models.TextChoices):
        API = "api", _("API")
        PUBLIC_FORM = "public_form", _("Formularz publiczny")

    tenant = models.ForeignKey(
        "dotykacka.Tenant",
        on_delete=models.PROTECT,
        related_name="virtual_card_applications",
    )
    api_key = models.ForeignKey(
        VirtualCardApiKey,
        on_delete=models.PROTECT,
        related_name="applications",
        blank=True,
        null=True,
    )
    customer = models.OneToOneField(
        "dotykacka.Klient",
        on_delete=models.PROTECT,
        related_name="virtual_card_application",
    )
    card_design = models.ForeignKey(
        "dotykacka.CardDesign",
        on_delete=models.PROTECT,
        related_name="virtual_card_applications",
    )
    physical_card = models.OneToOneField(
        "dotykacka.PhysicalCard",
        on_delete=models.PROTECT,
        related_name="virtual_card_application",
        blank=True,
        null=True,
    )
    consent_record = models.OneToOneField(
        "customers.ConsentRecord",
        on_delete=models.PROTECT,
        related_name="virtual_card_application",
    )
    usage_event = models.OneToOneField(
        "billing.UsageEvent",
        on_delete=models.PROTECT,
        related_name="virtual_card_application",
        blank=True,
        null=True,
    )
    public_id = models.UUIDField(default=uuid4, unique=True, editable=False)
    idempotency_key = models.CharField(max_length=160)
    request_sha256 = models.CharField(max_length=64)
    source = models.CharField(max_length=24, choices=Source.choices)
    brand_snapshot = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("tenant", "idempotency_key"),
                name="unique_tenant_virtual_card_request",
            )
        ]
        ordering = ("-created_at", "-pk")

    def __str__(self):
        return f"{self.tenant}: {self.public_id}"

    def clean(self):
        errors = {}
        for name in ("customer", "card_design", "physical_card", "consent_record"):
            value = getattr(self, name, None)
            if value is not None and value.tenant_id != self.tenant_id:
                errors[name] = _("Wniosek i powiązane dane muszą należeć do jednej firmy.")
        if self.customer_id and self.physical_card_id:
            if self.physical_card.customer_id != self.customer_id:
                errors["physical_card"] = _("Wybrana karta musi być przypisana do tego klienta.")
        if self.api_key_id and self.api_key.tenant_id != self.tenant_id:
            errors["api_key"] = _("Klucz API musi należeć do tej samej firmy.")
        if self.usage_event_id and self.usage_event.tenant_id != self.tenant_id:
            errors["usage_event"] = _("Użycie musi należeć do tej samej firmy.")
        if errors:
            raise ValidationError(errors)


class VirtualCardFollowUp(AppendOnlyMixin, models.Model):
    """Durable jobs created for a virtual-card application."""

    application = models.ForeignKey(
        VirtualCardApplication,
        on_delete=models.PROTECT,
        related_name="followups",
    )
    integration_job = models.OneToOneField(
        "integrations.IntegrationJob",
        on_delete=models.PROTECT,
        related_name="virtual_card_followup",
    )
    kind = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("application", "kind"),
                name="unique_virtual_card_followup_kind",
            )
        ]
        ordering = ("created_at", "pk")

    def clean(self):
        errors = {}
        if (
            self.integration_job_id
            and self.application_id
            and self.integration_job.tenant_id != self.application.tenant_id
        ):
            errors["integration_job"] = _("Zadanie musi należeć do firmy wniosku.")
        if self.integration_job_id and self.kind != self.integration_job.kind:
            errors["kind"] = _("Rodzaj zadania musi odpowiadać zadaniu integracji.")
        if errors:
            raise ValidationError(errors)


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
                errors[name] = _("Zapisy rejestracji muszą należeć do jednej firmy.")
        if self.usage_event_id and self.usage_event.tenant_id != self.tenant_id:
            errors["usage_event"] = _("Użycie i rejestracja muszą należeć do tej samej firmy.")
        if self.brand_revision_id and self.brand_revision.tenant_id != self.tenant_id:
            errors["brand_revision"] = _("Wersja marki i rejestracja muszą należeć do tej samej firmy.")
        if self.card_design_id and self.card_design.tenant_id != self.tenant_id:
            errors["card_design"] = _("Projekt karty i rejestracja muszą należeć do tej samej firmy.")
        if self.customer_id and self.physical_card_id:
            if self.physical_card.customer_id != self.customer_id:
                errors["physical_card"] = _("Karta musi być przypisana do rejestrowanego klienta.")
        if errors:
            raise ValidationError(errors)


class EnrollmentAccessLink(AppendOnlyMixin, models.Model):
    class Purpose(models.TextChoices):
        WALLET_STATUS = "wallet_status", _("Status Wallet i zadań dodatkowych")

    class Reason(models.TextChoices):
        REGISTRATION = "registration", _("Rejestracja")
        RESEND = "resend", _("Jawne ponowne wysłanie")

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
        INITIAL = "initial", _("Pierwsza rejestracja")
        RESEND = "resend", _("Jawne ponowne wysłanie")

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

    def get_kind_display(self):
        labels = {
            "wallet.apple.issue": _("Wydanie karty Apple Wallet"),
            "wallet.google.issue": _("Wydanie karty Google Wallet"),
            "pos.dotykacka.customer_upsert": _("Synchronizacja klienta z Dotykačka"),
            "communications.brevo.contact_upsert": _("Synchronizacja kontaktu z Brevo"),
            "communications.email.pass": _("Wiadomość e-mail z kartą"),
        }
        return labels.get(self.kind, self.kind)

    def clean(self):
        if (
            self.integration_job_id
            and self.enrollment_id
            and self.integration_job.tenant_id != self.enrollment.tenant_id
        ):
            raise ValidationError(
                {"integration_job": _("Zadanie dodatkowe i rejestracja muszą należeć do tej samej firmy.")}
            )
        if self.integration_job_id and self.kind != self.integration_job.kind:
            raise ValidationError({"kind": _("Rodzaj zadania dodatkowego musi odpowiadać rodzajowi zadania integracji.")})


class EnrollmentEvent(AppendOnlyMixin, models.Model):
    class Kind(models.TextChoices):
        REGISTERED = "registered", _("Zarejestrowano")
        CARD_ASSIGNED = "card_assigned", _("Przypisano kartę")
        CONSENT_RECORDED = "consent_recorded", _("Zapisano zgodę")
        ISSUANCE_RECORDED = "issuance_recorded", _("Zapisano wydanie")
        FOLLOWUPS_ENQUEUED = "followups_enqueued", _("Dodano zadania dodatkowe")
        RETRY_REQUESTED = "retry_requested", _("Zlecono ponowienie")
        RESEND_REQUESTED = "resend_requested", _("Zlecono ponowne wysłanie")

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
                {"integration_job": _("Zadanie zdarzenia i rejestracja muszą należeć do tej samej firmy.")}
            )


__all__ = [
    "Enrollment",
    "EnrollmentAccessLink",
    "EnrollmentEvent",
    "EnrollmentFollowUp",
    "VirtualCardApiKey",
    "VirtualCardApplication",
    "VirtualCardFollowUp",
]
