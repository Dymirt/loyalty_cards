"""Public loyalty-card enrollment form."""

from django import forms

from cards.codes import CardCodeError, parse_card_code
from cards.services import card_is_available
from customers.forms import CustomerProfileForm
from customers.models import Customer
from tenants.forms import style_portal_form


class LoyaltyCustomerRegistrationForm(CustomerProfileForm):
    barcode = forms.CharField(max_length=60, label="Barcode")
    marketing_consent = forms.BooleanField(required=True, label="Zgoda marketingowa")

    def __init__(self, *args, tenant, **kwargs):
        self.tenant = tenant
        super().__init__(*args, **kwargs)
        style_portal_form(self)
        if hasattr(tenant, "brand") and tenant.brand.marketing_consent_text:
            self.fields["marketing_consent"].label = tenant.brand.marketing_consent_text

    def clean_barcode(self):
        try:
            barcode = parse_card_code(
                self.cleaned_data["barcode"],
                expected_prefix=self.tenant.card_prefix,
            ).value
        except CardCodeError as exc:
            raise forms.ValidationError("Nieprawidłowy format kodu kreskowego.") from exc
        if Customer.objects.filter(tenant=self.tenant, klient_id=barcode).exists():
            raise forms.ValidationError("Ta karta już istnieje w bazie danych.")
        if not card_is_available(tenant=self.tenant, code=barcode):
            raise forms.ValidationError("Ta karta nie należy do dostępnej puli kart.")
        return barcode


def registration_form_data(post_data):
    """Accept old field names while new templates use Python-style names."""

    data = post_data.copy()
    aliases = {"first_name": "firstName", "last_name": "lastName", "phone": "tel"}
    for current_name, legacy_name in aliases.items():
        if current_name not in data and legacy_name in data:
            data[current_name] = data[legacy_name]
    return data
