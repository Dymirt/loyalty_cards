"""Tenant profile forms and shared portal form styling."""

from django import forms

from .models import TenantBrand


PORTAL_INPUT_CLASSES = (
    "portal-input disabled:cursor-not-allowed disabled:bg-stone-100 "
    "disabled:text-stone-500"
)
PORTAL_CHECKBOX_CLASSES = (
    "mt-1 size-5 rounded border-stone-300 text-accent-700 "
    "focus:ring-2 focus:ring-accent-100"
)


def style_portal_form(form):
    for name, field in form.fields.items():
        classes = (
            PORTAL_CHECKBOX_CLASSES
            if isinstance(field.widget, forms.CheckboxInput)
            else PORTAL_INPUT_CLASSES
        )
        field.widget.attrs["class"] = classes
        if field.help_text:
            field.widget.attrs["aria-describedby"] = f"{form[name].id_for_label}_help"


class TenantBrandForm(forms.ModelForm):
    class Meta:
        model = TenantBrand
        fields = (
            "public_name",
            "tagline",
            "address",
            "phone",
            "email",
            "website_url",
            "email_subject",
            "email_signature",
            "marketing_consent_text",
        )
        labels = {
            "public_name": "Nazwa publiczna",
            "tagline": "Hasło marki",
            "address": "Adres",
            "phone": "Telefon",
            "email": "E-mail",
            "website_url": "Strona WWW",
            "email_subject": "Temat wiadomości z kartą",
            "email_signature": "Podpis wiadomości",
            "marketing_consent_text": "Treść zgody marketingowej",
        }
        widgets = {
            "address": forms.Textarea(attrs={"rows": 3}),
            "marketing_consent_text": forms.Textarea(attrs={"rows": 4}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        style_portal_form(self)
