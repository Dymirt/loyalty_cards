"""Tenant-owned Brevo configuration form."""

from django import forms
from django.utils.translation import gettext_lazy as _

from integrations.models import IntegrationConnection
from tenants.forms import style_portal_form


class BrevoIntegrationForm(forms.Form):
    enabled = forms.BooleanField(required=False, label=_("Włącz integrację"))
    list_id = forms.IntegerField(min_value=1, required=False, label=_("ID listy"))
    default_phone_country_code = forms.RegexField(
        regex=r"^\+[1-9][0-9]{0,3}$",
        required=False,
        label=_("Domyślny kod kraju"),
    )
    api_key = forms.CharField(
        required=False,
        label=_("Klucz API"),
        widget=forms.PasswordInput(render_value=False),
        help_text=_("Pozostaw puste, aby zachować zaszyfrowany klucz."),
    )

    def __init__(self, *args, tenant, connection=None, **kwargs):
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
        style_portal_form(self)

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("enabled"):
            if not cleaned.get("list_id"):
                self.add_error(
                    "list_id", _("To pole jest wymagane dla aktywnej integracji.")
                )
            if not cleaned.get("api_key") and not self.connection.has_secret("api_key"):
                self.add_error(
                    "api_key", _("Klucz jest wymagany dla aktywnej integracji.")
                )
        return cleaned

    def save(self):
        configuration = dict(self.connection.configuration)
        configuration.update(
            {
                "list_id": self.cleaned_data.get("list_id") or 0,
                "default_phone_country_code": self.cleaned_data.get(
                    "default_phone_country_code"
                )
                or "+48",
            }
        )
        self.connection.configuration = configuration
        credentials = self.connection.get_credentials()
        if self.cleaned_data.get("api_key"):
            credentials["api_key"] = self.cleaned_data["api_key"]
        self.connection.set_credentials(credentials)
        self.connection.enabled = self.cleaned_data["enabled"]
        self.connection.save()
        return self.connection


__all__ = ["BrevoIntegrationForm"]
