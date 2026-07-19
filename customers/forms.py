"""Forms for customer-owned profile fields."""

import re

from django import forms
from django.utils.translation import gettext_lazy as _

from tenants.forms import style_portal_form


class CustomerProfileForm(forms.Form):
    first_name = forms.CharField(max_length=100, label=_("Imię"))
    last_name = forms.CharField(max_length=100, label=_("Nazwisko"))
    email = forms.EmailField(max_length=100, label=_("E-mail"))
    phone = forms.CharField(max_length=20, label=_("Telefon"))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        style_portal_form(self)

    def clean_phone(self):
        phone = self.cleaned_data["phone"].strip()
        if not re.fullmatch(r"[1-9][0-9]{8}", phone):
            raise forms.ValidationError(_("Podaj 9-cyfrowy numer telefonu."))
        return phone
