"""Django forms for public loyalty-card registration."""

import re

from django import forms

from .card_codes import CardCodeError, normalize_card_code
from .models import Klient


class LoyaltyCustomerRegistrationForm(forms.Form):
    first_name = forms.CharField(max_length=100, label="Imię")
    last_name = forms.CharField(max_length=100, label="Nazwisko")
    email = forms.EmailField(max_length=100, label="E-mail")
    phone = forms.CharField(max_length=20, label="Tel.")
    barcode = forms.CharField(max_length=60, label="Barcode")
    marketing_consent = forms.BooleanField(
        required=True,
        label=(
            "Wyrażam zgodę na kontakt i przesyłanie treści marketingowych dla firmy "
            "Centrum Concept Sp. z o.o. Marta Banaszek Atelier-Cafe"
        ),
    )

    def clean_phone(self) -> str:
        phone = self.cleaned_data["phone"].strip()
        if not re.fullmatch(r"[1-9][0-9]{8}", phone):
            raise forms.ValidationError("Podaj 9-cyfrowy numer telefonu.")
        return phone

    def clean_barcode(self) -> str:
        try:
            barcode = normalize_card_code(self.cleaned_data["barcode"])
        except CardCodeError as exc:
            raise forms.ValidationError("Nieprawidłowy format kodu kreskowego.") from exc

        if Klient.objects.filter(klient_id=barcode).exists():
            raise forms.ValidationError("Ta karta już istnieje w bazie danych.")
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
