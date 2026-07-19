"""Subscription, entitlement, usage, and commercial snapshot records."""

from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, RegexValidator
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _


currency_validator = RegexValidator(
    regex=r"^[A-Z]{3}$",
    message="Use a three-letter ISO 4217 currency code, for example PLN.",
)
money_validators = [MinValueValidator(Decimal("0.00"))]


class AppendOnlyMixin:
    """Protect history records from application-level rewrites and deletes."""

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError(_("Zapisy historyczne są tylko do dopisywania."))
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError(_("Zapisów historycznych nie można usuwać."))


class Plan(models.Model):
    code = models.SlugField(max_length=60, unique=True)
    name = models.CharField(max_length=120)
    public_description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("name",)

    def __str__(self):
        return self.name


class PlanVersion(models.Model):
    class BillingInterval(models.TextChoices):
        MONTHLY = "monthly", _("Miesięcznie")
        YEARLY = "yearly", _("Rocznie")

    class TaxDisplay(models.TextChoices):
        INCLUSIVE = "inclusive", _("Podatek wliczony")
        EXCLUSIVE = "exclusive", _("Podatek doliczany")
        NOT_APPLICABLE = "not_applicable", _("Podatek nie dotyczy")

    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name="versions")
    version = models.PositiveIntegerField()
    billing_interval = models.CharField(
        max_length=16,
        choices=BillingInterval.choices,
        default=BillingInterval.MONTHLY,
    )
    recurring_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=money_validators,
    )
    currency = models.CharField(
        max_length=3,
        default="PLN",
        validators=[currency_validator],
    )
    tax_display = models.CharField(
        max_length=20,
        choices=TaxDisplay.choices,
        default=TaxDisplay.INCLUSIVE,
    )
    tax_rate = models.DecimalField(
        max_digits=6,
        decimal_places=4,
        default=Decimal("0.0000"),
        validators=[MinValueValidator(Decimal("0.0000"))],
        help_text=_("Stawka dziesiętna, na przykład 0.2300 dla 23%."),
    )
    published_at = models.DateTimeField(blank=True, null=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_plan_versions",
        blank=True,
        null=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("plan", "version"),
                name="billing_unique_plan_version",
            )
        ]
        ordering = ("plan__name", "-version")

    def clean(self):
        self.currency = (self.currency or "").upper()
        if self.tax_rate > Decimal("1.0000"):
            raise ValidationError({"tax_rate": _("Stawka podatku nie może przekraczać 100%.")})

    def save(self, *args, **kwargs):
        self.currency = (self.currency or "").upper()
        if self.pk:
            previous = type(self).objects.get(pk=self.pk)
            if previous.published_at:
                raise ValidationError(_("Opublikowanych wersji planu nie można zmieniać."))
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.published_at:
            raise ValidationError(_("Opublikowanych wersji planu nie można usuwać."))
        return super().delete(*args, **kwargs)

    def __str__(self):
        return f"{self.plan} v{self.version}"


class EntitlementPolicy(models.Model):
    plan_version = models.OneToOneField(
        PlanVersion,
        on_delete=models.PROTECT,
        related_name="entitlement_policy",
    )
    active_seat_limit = models.PositiveIntegerField(blank=True, null=True)
    card_issuance_limit = models.PositiveIntegerField(blank=True, null=True)
    included_print_quantity = models.PositiveIntegerField(default=0)
    unused_allowance_rolls_over = models.BooleanField(default=False)
    print_overage_allowed = models.BooleanField(default=True)

    def save(self, *args, **kwargs):
        if self.pk:
            previous = type(self).objects.select_related("plan_version").get(pk=self.pk)
            if previous.plan_version.published_at:
                raise ValidationError(_("Opublikowanych zasad limitów nie można zmieniać."))
        elif self.plan_version_id and self.plan_version.published_at:
            raise ValidationError(_("Dodaj zasady limitów przed opublikowaniem planu."))
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.plan_version.published_at:
            raise ValidationError(_("Opublikowanych zasad limitów nie można usuwać."))
        return super().delete(*args, **kwargs)

    def __str__(self):
        return f"Entitlements for {self.plan_version}"


class TenantSubscription(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", _("Szkic")
        ACTIVE = "active", _("Aktywna")
        PAUSED = "paused", _("Wstrzymana")
        CANCELLED = "cancelled", _("Anulowana")

    tenant = models.ForeignKey(
        "dotykacka.Tenant",
        on_delete=models.PROTECT,
        related_name="subscriptions",
    )
    plan_version = models.ForeignKey(
        PlanVersion,
        on_delete=models.PROTECT,
        related_name="subscriptions",
    )
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-starts_at", "-pk")

    def clean(self):
        errors = {}
        if self.ends_at and self.ends_at <= self.starts_at:
            errors["ends_at"] = _("Data zakończenia musi być późniejsza niż data rozpoczęcia.")
        if self.status == self.Status.ACTIVE and not self.plan_version.published_at:
            errors["plan_version"] = _("Można aktywować tylko opublikowaną wersję planu.")
        if self.status == self.Status.ACTIVE and self.tenant_id and self.starts_at:
            overlaps = type(self).objects.filter(
                tenant_id=self.tenant_id,
                status=self.Status.ACTIVE,
            ).exclude(pk=self.pk)
            if self.ends_at:
                overlaps = overlaps.filter(starts_at__lt=self.ends_at)
            overlaps = overlaps.filter(Q(ends_at__isnull=True) | Q(ends_at__gt=self.starts_at))
            if overlaps.exists():
                errors["status"] = _("Ta firma ma już aktywną subskrypcję w tym okresie.")
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.pk:
            previous = type(self).objects.get(pk=self.pk)
            for field_name in ("tenant_id", "plan_version_id", "starts_at"):
                if getattr(previous, field_name) != getattr(self, field_name):
                    raise ValidationError(
                        _("Firmy, wersji planu i początku subskrypcji nie można zmieniać.")
                    )
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError(_("Subskrypcji nie można usuwać."))

    def __str__(self):
        return f"{self.tenant}: {self.plan_version}"


class BillingPeriod(models.Model):
    class Status(models.TextChoices):
        OPEN = "open", _("Otwarty")
        CLOSED = "closed", _("Zamknięty")

    subscription = models.ForeignKey(
        TenantSubscription,
        on_delete=models.PROTECT,
        related_name="billing_periods",
    )
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.OPEN)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("subscription", "starts_at", "ends_at"),
                name="billing_unique_subscription_period",
            ),
            models.CheckConstraint(
                condition=Q(ends_at__gt=models.F("starts_at")),
                name="billing_period_end_after_start",
            ),
        ]
        ordering = ("-starts_at",)

    def __str__(self):
        return f"{self.subscription} ({self.starts_at:%Y-%m-%d})"

    def save(self, *args, **kwargs):
        if self.pk:
            previous = type(self).objects.get(pk=self.pk)
            for field_name in ("subscription_id", "starts_at", "ends_at"):
                if getattr(previous, field_name) != getattr(self, field_name):
                    raise ValidationError(_("Granic okresu rozliczeniowego nie można zmieniać."))
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError(_("Okresów rozliczeniowych nie można usuwać."))


class UsageEvent(AppendOnlyMixin, models.Model):
    class Kind(models.TextChoices):
        PHYSICAL_CARD_ISSUED = "physical_card_issued", _("Wydano kartę fizyczną")
        VIRTUAL_CARD_ISSUED = "virtual_card_issued", _("Wydano kartę cyfrową")
        PHYSICAL_CARD_PRODUCED = "physical_card_produced", _("Wyprodukowano kartę fizyczną")

    tenant = models.ForeignKey(
        "dotykacka.Tenant",
        on_delete=models.PROTECT,
        related_name="billing_usage_events",
    )
    subscription = models.ForeignKey(
        TenantSubscription,
        on_delete=models.PROTECT,
        related_name="usage_events",
    )
    billing_period = models.ForeignKey(
        BillingPeriod,
        on_delete=models.PROTECT,
        related_name="usage_events",
    )
    kind = models.CharField(max_length=32, choices=Kind.choices)
    quantity = models.PositiveIntegerField(default=1)
    idempotency_key = models.CharField(max_length=180)
    reference_type = models.CharField(max_length=80, blank=True)
    reference_id = models.CharField(max_length=120, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    occurred_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("tenant", "idempotency_key"),
                name="billing_unique_tenant_usage_key",
            ),
            models.CheckConstraint(
                condition=Q(quantity__gt=0),
                name="billing_usage_quantity_positive",
            ),
        ]
        ordering = ("-occurred_at", "-pk")

    def clean(self):
        errors = {}
        if self.subscription_id and self.subscription.tenant_id != self.tenant_id:
            errors["subscription"] = _("Subskrypcja musi należeć do firmy rejestrującej użycie.")
        if (
            self.billing_period_id
            and self.billing_period.subscription_id != self.subscription_id
        ):
            errors["billing_period"] = _("Okres rozliczeniowy musi należeć do subskrypcji.")
        if errors:
            raise ValidationError(errors)


class PriceBook(models.Model):
    code = models.SlugField(max_length=60, unique=True)
    name = models.CharField(max_length=120)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("name",)

    def __str__(self):
        return self.name


class PriceBookVersion(models.Model):
    price_book = models.ForeignKey(
        PriceBook,
        on_delete=models.PROTECT,
        related_name="versions",
    )
    version = models.PositiveIntegerField()
    currency = models.CharField(
        max_length=3,
        default="PLN",
        validators=[currency_validator],
    )
    tax_display = models.CharField(
        max_length=20,
        choices=PlanVersion.TaxDisplay.choices,
        default=PlanVersion.TaxDisplay.INCLUSIVE,
    )
    tax_rate = models.DecimalField(
        max_digits=6,
        decimal_places=4,
        default=Decimal("0.0000"),
        validators=[MinValueValidator(Decimal("0.0000"))],
    )
    shipping_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=money_validators,
    )
    published_at = models.DateTimeField(blank=True, null=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_price_book_versions",
        blank=True,
        null=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("price_book", "version"),
                name="billing_unique_price_book_version",
            )
        ]
        ordering = ("price_book__name", "-version")

    def clean(self):
        self.currency = (self.currency or "").upper()
        if self.tax_rate > Decimal("1.0000"):
            raise ValidationError({"tax_rate": _("Stawka podatku nie może przekraczać 100%.")})

    def save(self, *args, **kwargs):
        self.currency = (self.currency or "").upper()
        if self.pk:
            previous = type(self).objects.get(pk=self.pk)
            if previous.published_at:
                raise ValidationError(_("Opublikowanych wersji cennika nie można zmieniać."))
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.published_at:
            raise ValidationError(_("Opublikowanych wersji cennika nie można usuwać."))
        return super().delete(*args, **kwargs)

    def __str__(self):
        return f"{self.price_book} v{self.version} ({self.currency})"


class CardPriceTier(models.Model):
    price_book_version = models.ForeignKey(
        PriceBookVersion,
        on_delete=models.PROTECT,
        related_name="card_price_tiers",
    )
    minimum_quantity = models.PositiveIntegerField(default=1)
    maximum_quantity = models.PositiveIntegerField(blank=True, null=True)
    unit_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=money_validators,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("price_book_version", "minimum_quantity"),
                name="billing_unique_price_tier_start",
            ),
            models.CheckConstraint(
                condition=Q(minimum_quantity__gt=0),
                name="billing_price_tier_min_positive",
            ),
            models.CheckConstraint(
                condition=Q(maximum_quantity__isnull=True)
                | Q(maximum_quantity__gte=models.F("minimum_quantity")),
                name="billing_price_tier_valid_range",
            ),
        ]
        ordering = ("minimum_quantity",)

    def save(self, *args, **kwargs):
        if self.pk:
            previous = type(self).objects.select_related("price_book_version").get(pk=self.pk)
            if previous.price_book_version.published_at:
                raise ValidationError(_("Opublikowanych progów cenowych nie można zmieniać."))
        elif self.price_book_version_id and self.price_book_version.published_at:
            raise ValidationError(_("Dodaj progi cenowe przed opublikowaniem cennika."))
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.price_book_version.published_at:
            raise ValidationError(_("Opublikowanych progów cenowych nie można usuwać."))
        return super().delete(*args, **kwargs)


class CardPack(models.Model):
    tenant = models.ForeignKey(
        "dotykacka.Tenant",
        on_delete=models.PROTECT,
        related_name="card_packs",
    )
    price_book_version = models.ForeignKey(
        PriceBookVersion,
        on_delete=models.PROTECT,
        related_name="card_packs",
    )
    name = models.CharField(max_length=120)
    purchased_quantity = models.PositiveIntegerField()
    consumed_quantity = models.PositiveIntegerField(default=0)
    purchase_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=money_validators,
    )
    currency = models.CharField(max_length=3, validators=[currency_validator])
    expires_at = models.DateTimeField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("expires_at", "created_at", "pk")
        constraints = [
            models.CheckConstraint(
                condition=Q(purchased_quantity__gt=0),
                name="billing_card_pack_quantity_positive",
            ),
            models.CheckConstraint(
                condition=Q(consumed_quantity__lte=models.F("purchased_quantity")),
                name="billing_card_pack_not_overconsumed",
            ),
        ]

    def clean(self):
        self.currency = (self.currency or "").upper()
        errors = {}
        if self.price_book_version_id and self.currency != self.price_book_version.currency:
            errors["currency"] = _("Waluta pakietu musi odpowiadać walucie wersji cennika.")
        if self.consumed_quantity > self.purchased_quantity:
            errors["consumed_quantity"] = _("Wykorzystana liczba kart przekracza wielkość pakietu.")
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.currency = (self.currency or "").upper()
        if self.pk:
            previous = type(self).objects.get(pk=self.pk)
            for field_name in (
                "tenant_id",
                "price_book_version_id",
                "name",
                "purchased_quantity",
                "purchase_amount",
                "currency",
                "expires_at",
            ):
                if getattr(previous, field_name) != getattr(self, field_name):
                    raise ValidationError(_("Warunków kupionego pakietu kart nie można zmieniać."))
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError(_("Kupionych pakietów kart nie można usuwać."))


class Quote(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", _("Szkic")
        ACCEPTED = "accepted", _("Zaakceptowana")
        EXPIRED = "expired", _("Wygasła")
        CANCELLED = "cancelled", _("Anulowana")

    tenant = models.ForeignKey(
        "dotykacka.Tenant",
        on_delete=models.PROTECT,
        related_name="billing_quotes",
    )
    subscription = models.ForeignKey(
        TenantSubscription,
        on_delete=models.PROTECT,
        related_name="quotes",
    )
    billing_period = models.ForeignKey(
        BillingPeriod,
        on_delete=models.PROTECT,
        related_name="quotes",
    )
    price_book_version = models.ForeignKey(
        PriceBookVersion,
        on_delete=models.PROTECT,
        related_name="quotes",
    )
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    idempotency_key = models.CharField(max_length=180)
    quantity = models.PositiveIntegerField()
    included_quantity = models.PositiveIntegerField(default=0)
    pack_quantity = models.PositiveIntegerField(default=0)
    billable_quantity = models.PositiveIntegerField(default=0)
    currency = models.CharField(max_length=3, validators=[currency_validator])
    subtotal_amount = models.DecimalField(
        max_digits=12, decimal_places=2, validators=money_validators
    )
    shipping_amount = models.DecimalField(
        max_digits=12, decimal_places=2, validators=money_validators
    )
    tax_amount = models.DecimalField(
        max_digits=12, decimal_places=2, validators=money_validators
    )
    total_amount = models.DecimalField(
        max_digits=12, decimal_places=2, validators=money_validators
    )
    snapshot = models.JSONField(default=dict)
    accepted_at = models.DateTimeField(blank=True, null=True)
    expires_at = models.DateTimeField(blank=True, null=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_billing_quotes",
        blank=True,
        null=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("tenant", "idempotency_key"),
                name="billing_unique_tenant_quote_key",
            ),
            models.CheckConstraint(
                condition=Q(quantity__gt=0),
                name="billing_quote_quantity_positive",
            ),
        ]
        ordering = ("-created_at", "-pk")

    def clean(self):
        self.currency = (self.currency or "").upper()
        errors = {}
        if self.subscription_id and self.subscription.tenant_id != self.tenant_id:
            errors["subscription"] = _("Subskrypcja musi należeć do firmy wskazanej w kalkulacji.")
        if self.billing_period_id and self.billing_period.subscription_id != self.subscription_id:
            errors["billing_period"] = _("Okres rozliczeniowy musi należeć do subskrypcji.")
        if self.price_book_version_id and self.currency != self.price_book_version.currency:
            errors["currency"] = _("Waluta kalkulacji musi odpowiadać walucie cennika.")
        if self.included_quantity + self.pack_quantity + self.billable_quantity != self.quantity:
            errors["quantity"] = _("Suma przydziałów kalkulacji musi odpowiadać liczbie kart.")
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.currency = (self.currency or "").upper()
        if self.pk:
            previous = type(self).objects.get(pk=self.pk)
            if previous.status == self.Status.ACCEPTED:
                raise ValidationError(_("Zaakceptowanych kalkulacji nie można zmieniać."))
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError(_("Kalkulacji nie można usuwać."))


class QuoteLine(AppendOnlyMixin, models.Model):
    class Kind(models.TextChoices):
        INCLUDED = "included", _("Limit w planie")
        PACK = "pack", _("Pakiet kart")
        PRODUCTION = "production", _("Produkcja kart")
        SHIPPING = "shipping", _("Wysyłka")
        TAX = "tax", _("Podatek")

    quote = models.ForeignKey(Quote, on_delete=models.PROTECT, related_name="lines")
    position = models.PositiveSmallIntegerField()
    kind = models.CharField(max_length=16, choices=Kind.choices)
    description = models.CharField(max_length=240)
    quantity = models.PositiveIntegerField(default=1)
    unit_amount = models.DecimalField(
        max_digits=12, decimal_places=2, validators=money_validators
    )
    total_amount = models.DecimalField(
        max_digits=12, decimal_places=2, validators=money_validators
    )
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("quote", "position"),
                name="billing_unique_quote_line_position",
            )
        ]
        ordering = ("position",)


class CardPackAllocation(AppendOnlyMixin, models.Model):
    quote = models.ForeignKey(
        Quote,
        on_delete=models.PROTECT,
        related_name="pack_allocations",
    )
    card_pack = models.ForeignKey(
        CardPack,
        on_delete=models.PROTECT,
        related_name="quote_allocations",
    )
    quantity = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("quote", "card_pack"),
                name="billing_unique_quote_pack_allocation",
            ),
            models.CheckConstraint(
                condition=Q(quantity__gt=0),
                name="billing_pack_allocation_positive",
            ),
        ]


class PrintQuoteConsumption(AppendOnlyMixin, models.Model):
    """One immutable conversion of an accepted quote into production usage."""

    quote = models.OneToOneField(
        Quote,
        on_delete=models.PROTECT,
        related_name="print_consumption",
    )
    usage_event = models.OneToOneField(
        UsageEvent,
        on_delete=models.PROTECT,
        related_name="print_quote_consumption",
    )
    included_quantity = models.PositiveIntegerField(default=0)
    pack_quantity = models.PositiveIntegerField(default=0)
    billable_quantity = models.PositiveIntegerField(default=0)
    reference_type = models.CharField(max_length=80)
    reference_id = models.CharField(max_length=120)
    consumed_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(included_quantity__gte=0),
                name="billing_consumption_included_nonnegative",
            ),
            models.CheckConstraint(
                condition=Q(pack_quantity__gte=0),
                name="billing_consumption_pack_nonnegative",
            ),
            models.CheckConstraint(
                condition=Q(billable_quantity__gte=0),
                name="billing_consumption_billable_nonnegative",
            ),
        ]

    def clean(self):
        errors = {}
        if self.quote_id and self.usage_event_id:
            if self.quote.tenant_id != self.usage_event.tenant_id:
                errors["usage_event"] = _("Użycie i kalkulacja muszą należeć do tej samej firmy.")
            if self.quote.billing_period_id != self.usage_event.billing_period_id:
                errors["usage_event"] = _("Użycie i kalkulacja muszą należeć do tego samego okresu rozliczeniowego.")
        if self.quote_id and (
            self.included_quantity + self.pack_quantity + self.billable_quantity
            != self.quote.quantity
        ):
            errors["included_quantity"] = _("Suma rozliczonego użycia musi odpowiadać liczbie kart w kalkulacji.")
        if errors:
            raise ValidationError(errors)
