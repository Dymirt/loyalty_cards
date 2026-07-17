import re

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from .tenant_secrets import decrypt_credentials, encrypt_credentials


class Tenant(models.Model):
    name = models.CharField(max_length=160)
    legal_name = models.CharField(max_length=200, blank=True)
    slug = models.SlugField(max_length=80, unique=True)
    card_prefix = models.CharField(max_length=10, unique=True)
    language_code = models.CharField(max_length=10, default="pl-pl")
    timezone = models.CharField(max_length=64, default="Europe/Warsaw")
    is_active = models.BooleanField(default=True)
    public_registration_enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self):
        self.card_prefix = (self.card_prefix or "").strip().upper()
        if not re.fullmatch(r"[A-Z][A-Z0-9]{0,9}", self.card_prefix):
            raise ValidationError({"card_prefix": "Use 1-10 uppercase letters or digits."})

    def save(self, *args, **kwargs):
        self.card_prefix = (self.card_prefix or "").strip().upper()
        return super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class TenantMembership(models.Model):
    class Role(models.TextChoices):
        OWNER = "owner", "Owner"
        STAFF = "staff", "Staff"

    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="memberships")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="tenant_memberships",
    )
    role = models.CharField(max_length=16, choices=Role.choices, default=Role.STAFF)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("tenant", "user"),
                name="unique_tenant_user_membership",
            )
        ]


class TenantBrand(models.Model):
    tenant = models.OneToOneField(Tenant, on_delete=models.PROTECT, related_name="brand")
    public_name = models.CharField(max_length=160)
    tagline = models.CharField(max_length=240, blank=True)
    address = models.TextField(blank=True)
    phone = models.CharField(max_length=40, blank=True)
    email = models.EmailField(blank=True)
    website_url = models.URLField(blank=True)
    logo_path = models.CharField(max_length=500, blank=True)
    background_image_path = models.CharField(max_length=500, blank=True)
    email_subject = models.CharField(max_length=240, blank=True)
    email_signature = models.CharField(max_length=240, blank=True)
    marketing_consent_text = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)


class IntegrationConnection(models.Model):
    class Provider(models.TextChoices):
        DOTYKACKA = "dotykacka", "Dotykačka"
        BREVO = "brevo", "Brevo"
        GOOGLE_WALLET = "google_wallet", "Google Wallet"

    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="integrations")
    provider = models.CharField(max_length=32, choices=Provider.choices)
    enabled = models.BooleanField(default=False)
    configuration = models.JSONField(default=dict, blank=True)
    credentials_encrypted = models.TextField(blank=True)
    last_tested_at = models.DateTimeField(blank=True, null=True)
    last_success_at = models.DateTimeField(blank=True, null=True)
    last_error_code = models.CharField(max_length=80, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("tenant", "provider"),
                name="unique_tenant_integration_provider",
            )
        ]

    def set_credentials(self, credentials: dict[str, str]) -> None:
        self.credentials_encrypted = encrypt_credentials(credentials)

    def get_credentials(self) -> dict[str, str]:
        return decrypt_credentials(self.credentials_encrypted)

    def get_secret(self, name: str, default="") -> str:
        return self.get_credentials().get(name, default)

    def has_secret(self, name: str) -> bool:
        return bool(self.get_secret(name))

    def __str__(self):
        return f"{self.tenant}: {self.get_provider_display()}"


class AccessToken(models.Model):
    connection = models.ForeignKey(
        IntegrationConnection,
        on_delete=models.PROTECT,
        related_name="access_tokens",
    )
    token = models.CharField(max_length=1000)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.created_at.strftime("%Y-%m-%d %H:%M:%S")


class Klient(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="customers")
    klient_id = models.CharField(max_length=60, unique=True)
    email = models.EmailField(max_length=100, blank=True, null=True)
    phone = models.CharField(max_length=20, blank=True, null=True)
    first_name = models.CharField(max_length=100, blank=True, null=True)
    last_name = models.CharField(max_length=100, blank=True, null=True)
    google_jwt_url = models.CharField(max_length=10000, blank=True, null=True)

    def __str__(self):
        return f"{self.first_name} {self.last_name} ({self.klient_id} ({self.pk}))"


class CardBatch(models.Model):
    class Status(models.TextChoices):
        LEGACY = "legacy", "Legacy imported"
        DRAFT = "draft", "Draft"
        GENERATED = "generated", "Generated"

    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="card_batches")
    name = models.CharField(max_length=160)
    card_prefix = models.CharField(max_length=10)
    start_number = models.PositiveIntegerField()
    end_number = models.PositiveIntegerField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    design_snapshot = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("tenant", "name"),
                name="unique_tenant_card_batch_name",
            )
        ]


class PhysicalCard(models.Model):
    class Status(models.TextChoices):
        AVAILABLE = "available", "Available"
        ASSIGNED = "assigned", "Assigned"
        PRINTED = "printed", "Printed"
        VOID = "void", "Void"

    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="physical_cards")
    batch = models.ForeignKey(CardBatch, on_delete=models.PROTECT, related_name="cards")
    customer = models.OneToOneField(
        Klient,
        on_delete=models.PROTECT,
        related_name="physical_card",
        blank=True,
        null=True,
    )
    code = models.CharField(max_length=60, unique=True)
    number = models.PositiveIntegerField()
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.AVAILABLE,
    )
    is_legacy = models.BooleanField(default=False)
    front_image_path = models.CharField(max_length=500, blank=True)
    back_image_path = models.CharField(max_length=500, blank=True)
    barcode_image_path = models.CharField(max_length=500, blank=True)
    cropped_image_path = models.CharField(max_length=500, blank=True)
    apple_pass_path = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("tenant", "number"),
                name="unique_tenant_physical_card_number",
            )
        ]


class AuditEvent(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="audit_events")
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="tenant_audit_events",
        blank=True,
        null=True,
    )
    action = models.CharField(max_length=120)
    object_type = models.CharField(max_length=120, blank=True)
    object_id = models.CharField(max_length=120, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
