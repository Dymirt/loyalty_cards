import re
from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

from .tenant_secrets import decrypt_credentials, encrypt_credentials


def _card_design_asset_path(instance, filename, asset_kind):
    extension = Path(filename).suffix.lower()
    if extension not in {".jpg", ".jpeg", ".png", ".webp"}:
        extension = ".bin"
    return (
        f"tenants/{instance.tenant.slug}/designs/v{instance.version:04d}/assets/"
        f"{asset_kind}-{uuid4().hex}{extension}"
    )


def card_design_background_path(instance, filename):
    return _card_design_asset_path(instance, filename, "background")


def card_design_logo_path(instance, filename):
    return _card_design_asset_path(instance, filename, "logo")


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
            raise ValidationError({"card_prefix": _("Użyj od 1 do 10 wielkich liter lub cyfr.")})

    def save(self, *args, **kwargs):
        self.card_prefix = (self.card_prefix or "").strip().upper()
        return super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class TenantMembership(models.Model):
    class Role(models.TextChoices):
        OWNER = "owner", _("Właściciel")
        STAFF = "staff", _("Pracownik")

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


class ImmutableVersionMixin:
    """Prevent published configuration and artifact records from being rewritten."""

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError(_("Opublikowanych wersji nie można zmieniać; utwórz nową wersję."))
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError(_("Opublikowanych wersji nie można usuwać."))


class TenantBrandRevision(ImmutableVersionMixin, models.Model):
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.PROTECT,
        related_name="brand_revisions",
    )
    version = models.PositiveIntegerField()
    public_name = models.CharField(max_length=160)
    tagline = models.CharField(max_length=240, blank=True)
    address = models.TextField(blank=True)
    phone = models.CharField(max_length=40, blank=True)
    email = models.EmailField(blank=True)
    website_url = models.URLField(blank=True)
    email_subject = models.CharField(max_length=240, blank=True)
    email_signature = models.CharField(max_length=240, blank=True)
    marketing_consent_text = models.TextField(blank=True)
    snapshot_checksum = models.CharField(max_length=64)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_brand_revisions",
        blank=True,
        null=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("tenant", "version"),
                name="unique_tenant_brand_revision_version",
            )
        ]
        ordering = ("-version",)

    def __str__(self):
        return f"{self.tenant} brand v{self.version}"


class CardDesign(ImmutableVersionMixin, models.Model):
    class CropMode(models.TextChoices):
        CENTER = "center", _("Kadrowanie centralne")
        FOCAL = "focal", _("Punkt centralny")
        DETERMINISTIC = "deterministic", _("Powtarzalne zróżnicowanie")

    class LayoutPreset(models.TextChoices):
        MARTA_LEGACY = "marta_legacy", _("Historyczny układ logo i tekstu")
        CENTERED = "centered", _("Wyśrodkowane logo i tekst")

    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="card_designs")
    brand_revision = models.ForeignKey(
        TenantBrandRevision,
        on_delete=models.PROTECT,
        related_name="card_designs",
    )
    version = models.PositiveIntegerField()
    name = models.CharField(max_length=160)
    background_source = models.ImageField(
        upload_to=card_design_background_path,
        max_length=500,
        blank=True,
    )
    logo = models.ImageField(
        upload_to=card_design_logo_path,
        max_length=500,
        blank=True,
    )
    layout_preset = models.CharField(
        max_length=32,
        choices=LayoutPreset.choices,
        default=LayoutPreset.CENTERED,
    )
    crop_mode = models.CharField(
        max_length=24,
        choices=CropMode.choices,
        default=CropMode.DETERMINISTIC,
    )
    focal_x = models.PositiveSmallIntegerField(default=50)
    focal_y = models.PositiveSmallIntegerField(default=50)
    width_px = models.PositiveIntegerField(default=1011)
    height_px = models.PositiveIntegerField(default=638)
    dpi = models.PositiveSmallIntegerField(default=300)
    bleed_mm = models.DecimalField(max_digits=4, decimal_places=1, default=0)
    logo_width_px = models.PositiveIntegerField(default=576)
    front_text = models.CharField(max_length=240, blank=True)
    back_text = models.TextField(blank=True)
    foreground_color = models.CharField(max_length=7, default="#000000")
    panel_color = models.CharField(max_length=7, default="#FFFFFF")
    barcode_foreground_color = models.CharField(max_length=7, default="#000000")
    barcode_background_color = models.CharField(max_length=7, default="#FFFFFF")
    font_family = models.CharField(max_length=40, default="barlow")
    design_checksum = models.CharField(max_length=64)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_card_designs",
        blank=True,
        null=True,
    )
    published_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("tenant", "version"),
                name="unique_tenant_card_design_version",
            ),
            models.UniqueConstraint(
                fields=("tenant", "design_checksum"),
                name="unique_tenant_card_design_checksum",
            ),
            models.CheckConstraint(
                condition=models.Q(focal_x__lte=100, focal_y__lte=100),
                name="card_design_focal_point_in_range",
            ),
        ]
        ordering = ("-version",)

    def clean(self):
        errors = {}
        for field_name in (
            "foreground_color",
            "panel_color",
            "barcode_foreground_color",
            "barcode_background_color",
        ):
            if not re.fullmatch(r"#[0-9A-Fa-f]{6}", getattr(self, field_name, "")):
                errors[field_name] = _("Użyj sześciocyfrowego koloru szesnastkowego, na przykład #000000.")
        if self.brand_revision_id and self.brand_revision.tenant_id != self.tenant_id:
            errors["brand_revision"] = _("Wersja marki musi należeć do tej samej firmy.")
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f"{self.tenant} card design v{self.version}"


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
        LEGACY = "legacy", _("Import historyczny")
        DRAFT = "draft", _("Szkic")
        GENERATED = "generated", _("Wygenerowana")

    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="card_batches")
    design = models.ForeignKey(
        CardDesign,
        on_delete=models.PROTECT,
        related_name="batches",
        blank=True,
        null=True,
    )
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
        AVAILABLE = "available", _("Dostępna")
        ASSIGNED = "assigned", _("Przypisana")
        PRINTED = "printed", _("Wydrukowana")
        VOID = "void", _("Unieważniona")

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


class CardArtifact(ImmutableVersionMixin, models.Model):
    class Kind(models.TextChoices):
        PROOF_FRONT = "proof_front", _("Próbka przodu")
        PROOF_BACK = "proof_back", _("Próbka tyłu")
        CARD_FRONT = "card_front", _("Przód karty")
        CARD_BACK = "card_back", _("Tył karty")
        BARCODE = "barcode", _("Kod kreskowy")
        MANIFEST = "manifest", _("Manifest")
        APPLE_PASS = "apple_pass", _("Karta Apple Wallet")
        GOOGLE_METADATA = "google_metadata", _("Metadane Google Wallet")

    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="card_artifacts")
    design = models.ForeignKey(CardDesign, on_delete=models.PROTECT, related_name="artifacts")
    batch = models.ForeignKey(
        CardBatch,
        on_delete=models.PROTECT,
        related_name="artifacts",
        blank=True,
        null=True,
    )
    physical_card = models.ForeignKey(
        PhysicalCard,
        on_delete=models.PROTECT,
        related_name="artifacts",
        blank=True,
        null=True,
    )
    storage_key = models.UUIDField(default=uuid4, unique=True, editable=False)
    kind = models.CharField(max_length=32, choices=Kind.choices)
    storage_path = models.CharField(max_length=700)
    sha256 = models.CharField(max_length=64)
    size_bytes = models.PositiveBigIntegerField()
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)

    def clean(self):
        errors = {}
        if self.design_id and self.design.tenant_id != self.tenant_id:
            errors["design"] = _("Projekt musi należeć do firmy przypisanej do pliku.")
        if self.batch_id and self.batch.tenant_id != self.tenant_id:
            errors["batch"] = _("Partia musi należeć do firmy przypisanej do pliku.")
        if self.physical_card_id and self.physical_card.tenant_id != self.tenant_id:
            errors["physical_card"] = _("Karta musi należeć do firmy przypisanej do pliku.")
        if errors:
            raise ValidationError(errors)


class WalletPass(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="wallet_passes")
    customer = models.OneToOneField(
        Klient,
        on_delete=models.PROTECT,
        related_name="wallet_pass",
    )
    physical_card = models.OneToOneField(
        PhysicalCard,
        on_delete=models.PROTECT,
        related_name="wallet_pass",
        blank=True,
        null=True,
    )
    apple_serial = models.UUIDField(default=uuid4, unique=True, editable=False)
    google_object_id = models.CharField(
        max_length=220,
        unique=True,
        blank=True,
        null=True,
    )
    google_save_url = models.CharField(max_length=10000, blank=True)
    apple_pass_path = models.CharField(max_length=700, blank=True)
    apple_pass_sha256 = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self):
        errors = {}
        if self.customer_id and self.customer.tenant_id != self.tenant_id:
            errors["customer"] = _("Klient musi należeć do firmy przypisanej do Wallet.")
        if self.physical_card_id and self.physical_card.tenant_id != self.tenant_id:
            errors["physical_card"] = _("Karta musi należeć do firmy przypisanej do Wallet.")
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.pk:
            previous = type(self).objects.get(pk=self.pk)
            for field_name in ("tenant_id", "customer_id", "physical_card_id", "apple_serial"):
                if getattr(previous, field_name) != getattr(self, field_name):
                    raise ValidationError(
                        _("Pola tożsamości Wallet %(field)s nie można zmieniać.")
                        % {"field": field_name}
                    )
            if (
                previous.google_object_id
                and self.google_object_id != previous.google_object_id
            ):
                raise ValidationError(_("Tożsamości obiektu Google Wallet nie można zmieniać."))
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError(_("Zapisów tożsamości Wallet nie można usuwać."))


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
