"""Public loyalty-card enrollment form."""

from uuid import uuid4

from django import forms
from django.utils.translation import gettext_lazy as _

from cards.codes import CardCodeError, parse_card_code
from cards.services import card_is_available
from customers.forms import CustomerProfileForm
from customers.models import Customer
from dotykacka.models import CardDesign
from tenants.forms import style_portal_form

from .catalog import virtual_card_designs


class LoyaltyCustomerRegistrationForm(CustomerProfileForm):
    barcode = forms.CharField(max_length=60, label=_("Kod karty"))
    marketing_consent = forms.BooleanField(
        required=True, label=_("Zgoda marketingowa")
    )
    tenant_confirmation = forms.CharField(required=False, widget=forms.HiddenInput)

    def __init__(self, *args, tenant, brand_snapshot=None, **kwargs):
        self.tenant = tenant
        self.brand_snapshot = brand_snapshot or {}
        super().__init__(*args, **kwargs)
        style_portal_form(self)
        consent_text = self.brand_snapshot.get("marketing_consent_text")
        if not consent_text and hasattr(tenant, "brand"):
            consent_text = tenant.brand.marketing_consent_text
        if consent_text:
            self.fields["marketing_consent"].label = consent_text

    def clean_barcode(self):
        try:
            barcode = parse_card_code(
                self.cleaned_data["barcode"],
                expected_prefix=self.tenant.card_prefix,
                max_number=2_147_483_647,
            ).value
        except CardCodeError as exc:
            raise forms.ValidationError(
                _("Nieprawidłowy format kodu kreskowego.")
            ) from exc
        if Customer.objects.filter(tenant=self.tenant, klient_id=barcode).exists():
            raise forms.ValidationError(_("Ta karta już istnieje w bazie danych."))
        if not card_is_available(tenant=self.tenant, code=barcode):
            raise forms.ValidationError(
                _("Ta karta nie należy do dostępnej puli kart.")
            )
        return barcode


class VirtualCardRegistrationForm(CustomerProfileForm):
    card_design = forms.ModelChoiceField(
        queryset=CardDesign.objects.none(),
        label=_("Wygląd karty"),
        empty_label=None,
    )
    marketing_consent = forms.BooleanField(
        required=True,
        label=_("Zgoda marketingowa"),
    )
    request_id = forms.UUIDField(widget=forms.HiddenInput)

    def __init__(self, *args, tenant, **kwargs):
        self.tenant = tenant
        kwargs.setdefault("initial", {})
        kwargs["initial"].setdefault("request_id", uuid4())
        super().__init__(*args, **kwargs)
        self.fields["card_design"].queryset = virtual_card_designs(tenant)
        if not self.is_bound:
            first_design = self.fields["card_design"].queryset.first()
            if first_design is not None:
                self.initial.setdefault("card_design", first_design.pk)
        consent_text = tenant.brand.marketing_consent_text
        if consent_text:
            self.fields["marketing_consent"].label = consent_text
        style_portal_form(self)


class VirtualCardApiKeyCreateForm(forms.Form):
    name = forms.CharField(
        max_length=160,
        label=_("Nazwa klucza"),
        help_text=_("Np. formularz strony Atelier Café albo integracja CRM."),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        style_portal_form(self)


def registration_form_data(post_data):
    """Accept old field names while new templates use Python-style names."""

    data = post_data.copy()
    aliases = {"first_name": "firstName", "last_name": "lastName", "phone": "tel"}
    for current_name, legacy_name in aliases.items():
        if current_name not in data and legacy_name in data:
            data[current_name] = data[legacy_name]
    return data


class FollowUpActionForm(forms.Form):
    reason = forms.CharField(
        label=_("Powód operacji"),
        widget=forms.Textarea(attrs={"rows": 2}),
    )
    idempotency_key = forms.CharField(widget=forms.HiddenInput)

    def __init__(self, *args, action, **kwargs):
        kwargs.setdefault("initial", {})
        kwargs["initial"].setdefault("idempotency_key", f"{action}:{uuid4()}")
        super().__init__(*args, **kwargs)
        style_portal_form(self)
