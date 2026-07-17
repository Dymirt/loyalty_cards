"""Django forms for public loyalty-card registration."""

import re

from django import forms

from .card_codes import CardCodeError, parse_card_code
from .models import IntegrationConnection, Klient, PhysicalCard, Tenant


class LoyaltyCustomerRegistrationForm(forms.Form):
    first_name = forms.CharField(max_length=100, label="Imię")
    last_name = forms.CharField(max_length=100, label="Nazwisko")
    email = forms.EmailField(max_length=100, label="E-mail")
    phone = forms.CharField(max_length=20, label="Tel.")
    barcode = forms.CharField(max_length=60, label="Barcode")
    marketing_consent = forms.BooleanField(
        required=True,
        label="Zgoda marketingowa",
    )

    def __init__(self, *args, tenant: Tenant, **kwargs):
        super().__init__(*args, **kwargs)
        self.tenant = tenant
        if hasattr(tenant, "brand") and tenant.brand.marketing_consent_text:
            self.fields["marketing_consent"].label = tenant.brand.marketing_consent_text

    def clean_phone(self) -> str:
        phone = self.cleaned_data["phone"].strip()
        if not re.fullmatch(r"[1-9][0-9]{8}", phone):
            raise forms.ValidationError("Podaj 9-cyfrowy numer telefonu.")
        return phone

    def clean_barcode(self) -> str:
        try:
            barcode = parse_card_code(
                self.cleaned_data["barcode"],
                expected_prefix=self.tenant.card_prefix,
            ).value
        except CardCodeError as exc:
            raise forms.ValidationError("Nieprawidłowy format kodu kreskowego.") from exc

        if Klient.objects.filter(tenant=self.tenant, klient_id=barcode).exists():
            raise forms.ValidationError("Ta karta już istnieje w bazie danych.")
        card = PhysicalCard.objects.filter(tenant=self.tenant, code=barcode).first()
        if card is None:
            raise forms.ValidationError("Ta karta nie należy do dostępnej puli kart.")
        if card.customer_id or card.status != PhysicalCard.Status.AVAILABLE:
            raise forms.ValidationError("Ta karta została już przypisana.")
        return barcode


def registration_form_data(post_data):
    """Accept old field names while new templates use Python-style names."""

    data = post_data.copy()
    aliases = {
        "first_name": "firstName",
        "last_name": "lastName",
        "phone": "tel",
    }
    for current_name, legacy_name in aliases.items():
        if current_name not in data and legacy_name in data:
            data[current_name] = data[legacy_name]
    return data


class DotykackaIntegrationForm(forms.Form):
    enabled = forms.BooleanField(required=False)
    cloud_id = forms.IntegerField(min_value=1, required=False)
    discount_group_id = forms.IntegerField(min_value=1, required=False)
    authorization_token = forms.CharField(
        required=False,
        widget=forms.PasswordInput(render_value=False),
        help_text="Pozostaw puste, aby zachować zapisany token.",
    )

    def __init__(self, *args, tenant: Tenant, connection=None, **kwargs):
        self.tenant = tenant
        self.connection = connection or IntegrationConnection(
            tenant=tenant,
            provider=IntegrationConnection.Provider.DOTYKACKA,
        )
        if not args and "data" not in kwargs:
            kwargs["initial"] = {
                "enabled": self.connection.enabled,
                "cloud_id": self.connection.configuration.get("cloud_id"),
                "discount_group_id": self.connection.configuration.get(
                    "discount_group_id"
                ),
            }
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("enabled"):
            for field in ("cloud_id", "discount_group_id"):
                if not cleaned.get(field):
                    self.add_error(field, "To pole jest wymagane dla aktywnej integracji.")
            if not cleaned.get("authorization_token") and not self.connection.has_secret(
                "authorization_token"
            ):
                self.add_error(
                    "authorization_token",
                    "Token jest wymagany dla aktywnej integracji.",
                )
        return cleaned

    def save(self):
        self.connection.configuration = {
            "cloud_id": self.cleaned_data.get("cloud_id") or 0,
            "discount_group_id": self.cleaned_data.get("discount_group_id") or 0,
        }
        credentials = self.connection.get_credentials()
        if self.cleaned_data.get("authorization_token"):
            credentials["authorization_token"] = self.cleaned_data["authorization_token"]
        self.connection.set_credentials(credentials)
        self.connection.enabled = self.cleaned_data["enabled"]
        self.connection.save()
        return self.connection


class BrevoIntegrationForm(forms.Form):
    enabled = forms.BooleanField(required=False)
    list_id = forms.IntegerField(min_value=1, required=False)
    default_phone_country_code = forms.RegexField(
        regex=r"^\+[1-9][0-9]{0,3}$",
        required=False,
    )
    api_key = forms.CharField(
        required=False,
        widget=forms.PasswordInput(render_value=False),
        help_text="Pozostaw puste, aby zachować zapisany klucz.",
    )

    def __init__(self, *args, tenant: Tenant, connection=None, **kwargs):
        self.tenant = tenant
        self.connection = connection or IntegrationConnection(
            tenant=tenant,
            provider=IntegrationConnection.Provider.BREVO,
        )
        if not args and "data" not in kwargs:
            kwargs["initial"] = {
                "enabled": self.connection.enabled,
                "list_id": self.connection.configuration.get("list_id"),
                "default_phone_country_code": self.connection.configuration.get(
                    "default_phone_country_code", "+48"
                ),
            }
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("enabled"):
            if not cleaned.get("list_id"):
                self.add_error("list_id", "To pole jest wymagane dla aktywnej integracji.")
            if not cleaned.get("api_key") and not self.connection.has_secret("api_key"):
                self.add_error("api_key", "Klucz jest wymagany dla aktywnej integracji.")
        return cleaned

    def save(self):
        self.connection.configuration = {
            "list_id": self.cleaned_data.get("list_id") or 0,
            "default_phone_country_code": self.cleaned_data.get(
                "default_phone_country_code"
            )
            or "+48",
        }
        credentials = self.connection.get_credentials()
        if self.cleaned_data.get("api_key"):
            credentials["api_key"] = self.cleaned_data["api_key"]
        self.connection.set_credentials(credentials)
        self.connection.enabled = self.cleaned_data["enabled"]
        self.connection.save()
        return self.connection


class GoogleWalletIntegrationForm(forms.Form):
    enabled = forms.BooleanField(required=False)
    issuer_id = forms.CharField(max_length=100, required=False)
    class_suffix = forms.RegexField(
        regex=r"^[A-Za-z0-9_-]{1,64}$",
        required=False,
    )

    def __init__(self, *args, tenant: Tenant, connection=None, **kwargs):
        self.tenant = tenant
        self.connection = connection or IntegrationConnection(
            tenant=tenant,
            provider=IntegrationConnection.Provider.GOOGLE_WALLET,
        )
        if not args and "data" not in kwargs:
            kwargs["initial"] = {
                "enabled": self.connection.enabled,
                "issuer_id": self.connection.configuration.get("issuer_id"),
                "class_suffix": self.connection.configuration.get("class_suffix"),
            }
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("enabled"):
            for field in ("issuer_id", "class_suffix"):
                if not cleaned.get(field):
                    self.add_error(field, "To pole jest wymagane dla aktywnej integracji.")
        return cleaned

    def save(self):
        self.connection.configuration = {
            "issuer_id": self.cleaned_data.get("issuer_id") or "",
            "class_suffix": self.cleaned_data.get("class_suffix") or "",
        }
        self.connection.enabled = self.cleaned_data["enabled"]
        self.connection.save()
        return self.connection
