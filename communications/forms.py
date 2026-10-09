"""Tenant campaign composer and OpenAI connection forms."""

from datetime import timedelta

from django import forms
from django.conf import settings
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from integrations.models import IntegrationConnection
from tenants.forms import style_portal_form


class OpenAIIntegrationForm(forms.Form):
    enabled = forms.BooleanField(required=False, label=_("Włącz integrację"))
    model = forms.CharField(
        max_length=120,
        required=False,
        label=_("Model"),
        help_text=_("Model używany do przygotowania treści kampanii e-mail."),
    )
    api_key = forms.CharField(
        required=False,
        label=_("Klucz API OpenAI"),
        widget=forms.PasswordInput(render_value=False),
        help_text=_("Pozostaw puste, aby zachować dotychczasowy zaszyfrowany klucz."),
    )

    def __init__(self, *args, tenant, connection=None, **kwargs):
        self.tenant = tenant
        self.connection = connection or IntegrationConnection(
            tenant=tenant,
            provider="openai",
        )
        if not args and "data" not in kwargs:
            kwargs["initial"] = {
                "enabled": self.connection.enabled,
                "model": self.connection.configuration.get(
                    "model", settings.OPENAI_EMAIL_MODEL
                ),
            }
        super().__init__(*args, **kwargs)
        style_portal_form(self)

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("enabled"):
            if not cleaned.get("model"):
                self.add_error("model", _("Model jest wymagany dla aktywnej integracji."))
            if not cleaned.get("api_key") and not self.connection.has_secret("api_key"):
                self.add_error(
                    "api_key", _("Klucz API jest wymagany dla aktywnej integracji.")
                )
        return cleaned

    def save(self):
        configuration = dict(self.connection.configuration)
        configuration["model"] = self.cleaned_data.get("model") or settings.OPENAI_EMAIL_MODEL
        self.connection.configuration = configuration
        credentials = self.connection.get_credentials()
        if self.cleaned_data.get("api_key"):
            credentials["api_key"] = self.cleaned_data["api_key"]
        self.connection.set_credentials(credentials)
        self.connection.enabled = self.cleaned_data["enabled"]
        self.connection.save()
        return self.connection


class URLListField(forms.Field):
    widget = forms.Textarea

    def to_python(self, value):
        if not value:
            return []
        if isinstance(value, (list, tuple)):
            candidates = value
        else:
            candidates = str(value).splitlines()
        urls = []
        validator = forms.URLField()
        for candidate in candidates:
            candidate = str(candidate).strip()
            if candidate:
                urls.append(validator.clean(candidate))
        return urls

    def validate(self, value):
        super().validate(value)
        if len(value) > 8:
            raise forms.ValidationError(_("Możesz dodać maksymalnie 8 linków."))


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleImageField(forms.ImageField):
    widget = MultipleFileInput

    def clean(self, data, initial=None):
        if not data:
            return []
        values = data if isinstance(data, (list, tuple)) else [data]
        return [super(MultipleImageField, self).clean(value) for value in values]


class EmailCampaignForm(forms.Form):
    goal = forms.CharField(
        label=_("Cel komunikacji"),
        max_length=4000,
        widget=forms.Textarea(
            attrs={
                "rows": 7,
                "placeholder": _(
                    "Np. Zaproś stałych gości na jesienne śniadania i podkreśl, że w weekend otrzymają podwójne punkty."
                ),
            }
        ),
        help_text=_("Opisz odbiorców, ofertę, ton i najważniejsze wezwanie do działania."),
    )
    links = URLListField(
        required=False,
        label=_("Linki"),
        widget=forms.Textarea(
            attrs={
                "rows": 4,
                "placeholder": "https://twoja-firma.pl/oferta\nhttps://instagram.com/twoja-firma",
            }
        ),
        help_text=_("Jeden pełny adres w wierszu. AI może użyć ich jako przycisku lub kontekstu."),
    )
    images = MultipleImageField(
        required=False,
        label=_("Zdjęcia i materiały marki"),
        widget=MultipleFileInput(
            attrs={
                "accept": "image/jpeg,image/png,image/webp",
                "multiple": True,
            }
        ),
        help_text=_("Do 5 plików JPG, PNG lub WebP; łącznie maksymalnie 25 MB."),
    )
    scheduled_for = forms.DateTimeField(
        required=False,
        label=_("Termin wysyłki"),
        input_formats=("%Y-%m-%dT%H:%M",),
        widget=forms.DateTimeInput(
            format="%Y-%m-%dT%H:%M",
            attrs={"type": "datetime-local"},
        ),
        help_text=_("Godzina jest interpretowana w strefie czasowej firmy."),
    )

    def __init__(self, *args, campaign=None, action="save", **kwargs):
        self.campaign = campaign
        self.action = action
        if not args and "data" not in kwargs and campaign is not None:
            kwargs["initial"] = {
                "goal": campaign.goal,
                "links": "\n".join(campaign.reference_links),
                "scheduled_for": campaign.scheduled_for,
            }
        super().__init__(*args, **kwargs)
        self.fields["scheduled_for"].widget.attrs["min"] = (
            timezone.localtime() + timedelta(minutes=2)
        ).strftime("%Y-%m-%dT%H:%M")
        style_portal_form(self)

    def clean_images(self):
        images = self.cleaned_data.get("images") or []
        existing_count = self.campaign.assets.count() if self.campaign else 0
        if existing_count + len(images) > 5:
            raise forms.ValidationError(_("Kampania może zawierać maksymalnie 5 zdjęć."))
        total_size = 0
        for image in images:
            total_size += image.size
            if image.size > 10 * 1024 * 1024:
                raise forms.ValidationError(_("Jeden plik może mieć maksymalnie 10 MB."))
            opened = getattr(image, "image", None)
            if opened and opened.format not in {"JPEG", "PNG", "WEBP"}:
                raise forms.ValidationError(_("Dozwolone formaty to JPG, PNG i WebP."))
            if opened and opened.width * opened.height > 40_000_000:
                raise forms.ValidationError(_("Obraz może mieć maksymalnie 40 megapikseli."))
        if total_size > 25 * 1024 * 1024:
            raise forms.ValidationError(_("Nowe pliki mogą mieć łącznie maksymalnie 25 MB."))
        return images

    def clean_scheduled_for(self):
        value = self.cleaned_data.get("scheduled_for")
        if self.action == "schedule" and value is None:
            raise forms.ValidationError(_("Wybierz termin wysyłki."))
        if value is None:
            return value
        now = timezone.now()
        if value <= now + timedelta(minutes=1):
            raise forms.ValidationError(_("Termin wysyłki musi być co najmniej 2 minuty w przyszłości."))
        if value > now + timedelta(days=365):
            raise forms.ValidationError(_("Termin wysyłki nie może być dalszy niż rok."))
        return value


__all__ = ["EmailCampaignForm", "OpenAIIntegrationForm"]
