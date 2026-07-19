from uuid import uuid4

from django import forms


class MarketingLeadForm(forms.Form):
    full_name = forms.CharField(label="Imię i nazwisko", max_length=120)
    company_name = forms.CharField(label="Nazwa firmy", max_length=160)
    email = forms.EmailField(label="E-mail służbowy", max_length=254)
    phone = forms.CharField(label="Telefon (opcjonalnie)", max_length=40, required=False)
    message = forms.CharField(
        label="Jakiego programu lojalnościowego potrzebujesz?",
        max_length=4000,
        widget=forms.Textarea(attrs={"rows": 5}),
    )
    privacy_consent = forms.BooleanField(
        label="Wyrażam zgodę na kontakt w sprawie zapytania.",
    )
    submission_id = forms.UUIDField(widget=forms.HiddenInput)
    website = forms.CharField(required=False, widget=forms.HiddenInput)

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("initial", {})
        kwargs["initial"].setdefault("submission_id", uuid4())
        super().__init__(*args, **kwargs)
        for field in self.visible_fields():
            if isinstance(field.field.widget, forms.CheckboxInput):
                field.field.widget.attrs["class"] = "size-5 rounded border-stone-300 text-accent-700"
            else:
                field.field.widget.attrs["class"] = "portal-input"

    def clean_website(self):
        value = self.cleaned_data.get("website", "")
        if value:
            raise forms.ValidationError("Nie udało się wysłać formularza.")
        return value


__all__ = ["MarketingLeadForm"]
