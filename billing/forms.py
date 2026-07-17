"""Django forms for owner quotes and platform commercial publication."""

from decimal import Decimal

from django import forms
from django.db import transaction

from tenants.forms import style_portal_form

from .models import (
    CardPack,
    CardPriceTier,
    EntitlementPolicy,
    Plan,
    PlanVersion,
    PriceBook,
    PriceBookVersion,
    TenantSubscription,
)
from .services import publish_plan_version, publish_price_book_version


class StyledFormMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        style_portal_form(self)


class PrintQuoteForm(StyledFormMixin, forms.Form):
    quantity = forms.IntegerField(min_value=1, label="Liczba kart")
    price_book_version = forms.ModelChoiceField(
        queryset=PriceBookVersion.objects.none(),
        label="Cennik",
    )
    idempotency_key = forms.CharField(widget=forms.HiddenInput)

    def __init__(self, *args, currency=None, **kwargs):
        super().__init__(*args, **kwargs)
        queryset = PriceBookVersion.objects.filter(
            published_at__isnull=False,
            price_book__is_active=True,
        ).select_related("price_book")
        if currency:
            queryset = queryset.filter(currency=currency)
        self.fields["price_book_version"].queryset = queryset.order_by(
            "price_book__name", "-version"
        )


class PlanForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Plan
        fields = ("code", "name", "public_description", "is_active")


class PlanVersionPublishForm(StyledFormMixin, forms.Form):
    plan = forms.ModelChoiceField(queryset=Plan.objects.filter(is_active=True))
    version = forms.IntegerField(min_value=1)
    billing_interval = forms.ChoiceField(
        choices=PlanVersion.BillingInterval.choices,
        initial=PlanVersion.BillingInterval.MONTHLY,
    )
    recurring_amount = forms.DecimalField(min_value=0, decimal_places=2)
    currency = forms.CharField(min_length=3, max_length=3, initial="PLN")
    tax_display = forms.ChoiceField(
        choices=PlanVersion.TaxDisplay.choices,
        initial=PlanVersion.TaxDisplay.INCLUSIVE,
    )
    tax_rate = forms.DecimalField(
        min_value=0,
        max_value=1,
        decimal_places=4,
        initial=Decimal("0.0000"),
        help_text="Wpisz zatwierdzoną stawkę; 0.2300 oznacza 23%.",
    )
    active_seat_limit = forms.IntegerField(min_value=1, required=False)
    card_issuance_limit = forms.IntegerField(min_value=1, required=False)
    included_print_quantity = forms.IntegerField(min_value=0, initial=0)
    unused_allowance_rolls_over = forms.BooleanField(required=False)
    print_overage_allowed = forms.BooleanField(required=False, initial=True)

    @transaction.atomic
    def save(self, *, actor):
        version = PlanVersion.objects.create(
            plan=self.cleaned_data["plan"],
            version=self.cleaned_data["version"],
            billing_interval=self.cleaned_data["billing_interval"],
            recurring_amount=self.cleaned_data["recurring_amount"],
            currency=self.cleaned_data["currency"].upper(),
            tax_display=self.cleaned_data["tax_display"],
            tax_rate=self.cleaned_data["tax_rate"],
            created_by=actor,
        )
        EntitlementPolicy.objects.create(
            plan_version=version,
            active_seat_limit=self.cleaned_data["active_seat_limit"],
            card_issuance_limit=self.cleaned_data["card_issuance_limit"],
            included_print_quantity=self.cleaned_data["included_print_quantity"],
            unused_allowance_rolls_over=self.cleaned_data[
                "unused_allowance_rolls_over"
            ],
            print_overage_allowed=self.cleaned_data["print_overage_allowed"],
        )
        return publish_plan_version(plan_version=version, actor=actor)


class PriceBookForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = PriceBook
        fields = ("code", "name", "is_active")


class PriceBookVersionPublishForm(StyledFormMixin, forms.Form):
    price_book = forms.ModelChoiceField(queryset=PriceBook.objects.filter(is_active=True))
    version = forms.IntegerField(min_value=1)
    currency = forms.CharField(min_length=3, max_length=3, initial="PLN")
    tax_display = forms.ChoiceField(
        choices=PlanVersion.TaxDisplay.choices,
        initial=PlanVersion.TaxDisplay.INCLUSIVE,
    )
    tax_rate = forms.DecimalField(
        min_value=0,
        max_value=1,
        decimal_places=4,
        initial=Decimal("0.0000"),
    )
    shipping_amount = forms.DecimalField(min_value=0, decimal_places=2)
    tiers = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 4}),
        help_text="Jedna linia na próg: 1-99: 5.00 oraz ostatnia 100+: 4.00",
    )

    def clean_tiers(self):
        tiers = []
        for line_number, raw_line in enumerate(self.cleaned_data["tiers"].splitlines(), 1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                quantity_text, amount_text = [part.strip() for part in line.split(":", 1)]
                if quantity_text.endswith("+"):
                    minimum = int(quantity_text[:-1])
                    maximum = None
                else:
                    minimum_text, maximum_text = quantity_text.split("-", 1)
                    minimum, maximum = int(minimum_text), int(maximum_text)
                amount = Decimal(amount_text)
            except (ValueError, ArithmeticError) as exc:
                raise forms.ValidationError(
                    f"Nieprawidłowy próg w linii {line_number}."
                ) from exc
            if minimum < 1 or (maximum is not None and maximum < minimum) or amount < 0:
                raise forms.ValidationError(
                    f"Nieprawidłowy zakres lub cena w linii {line_number}."
                )
            tiers.append((minimum, maximum, amount))
        if not tiers:
            raise forms.ValidationError("Dodaj co najmniej jeden próg cenowy.")
        return tiers

    @transaction.atomic
    def save(self, *, actor):
        version = PriceBookVersion.objects.create(
            price_book=self.cleaned_data["price_book"],
            version=self.cleaned_data["version"],
            currency=self.cleaned_data["currency"].upper(),
            tax_display=self.cleaned_data["tax_display"],
            tax_rate=self.cleaned_data["tax_rate"],
            shipping_amount=self.cleaned_data["shipping_amount"],
            created_by=actor,
        )
        for minimum, maximum, amount in self.cleaned_data["tiers"]:
            CardPriceTier.objects.create(
                price_book_version=version,
                minimum_quantity=minimum,
                maximum_quantity=maximum,
                unit_amount=amount,
            )
        return publish_price_book_version(price_book_version=version, actor=actor)


class TenantSubscriptionForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = TenantSubscription
        fields = ("tenant", "plan_version", "status", "starts_at", "ends_at")
        widgets = {
            "starts_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "ends_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["plan_version"].queryset = PlanVersion.objects.filter(
            published_at__isnull=False,
            plan__is_active=True,
        )


class CardPackForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = CardPack
        fields = (
            "tenant",
            "price_book_version",
            "name",
            "purchased_quantity",
            "purchase_amount",
            "currency",
            "expires_at",
            "is_active",
        )
        widgets = {"expires_at": forms.DateTimeInput(attrs={"type": "datetime-local"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["price_book_version"].queryset = PriceBookVersion.objects.filter(
            published_at__isnull=False,
            price_book__is_active=True,
        )
