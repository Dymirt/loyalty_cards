"""Tenant-owned Dotykačka configuration form."""

from django import forms
from django.utils.translation import gettext_lazy as _

from integrations.models import IntegrationConnection
from tenants.forms import style_portal_form


class DotykackaIntegrationForm(forms.Form):
    enabled = forms.BooleanField(required=False, label=_("Włącz integrację"))
    discount_group_id = forms.IntegerField(
        min_value=1,
        required=False,
        label=_("ID grupy rabatowej"),
    )

    def __init__(self, *args, tenant, connection=None, **kwargs):
        self.tenant = tenant
        self.connection = connection or IntegrationConnection(
            tenant=tenant,
            provider=IntegrationConnection.Provider.DOTYKACKA,
        )
        if not args and "data" not in kwargs:
            kwargs["initial"] = {
                "enabled": self.connection.enabled,
                "discount_group_id": self.connection.configuration.get(
                    "discount_group_id"
                ),
            }
        super().__init__(*args, **kwargs)
        style_portal_form(self)

    def clean(self):
        cleaned = super().clean()
        has_refresh_token = self.connection.has_secret("refresh_token")
        has_cloud_id = bool(self.connection.configuration.get("cloud_id"))
        if cleaned.get("enabled"):
            if not cleaned.get("discount_group_id"):
                self.add_error(
                    "discount_group_id",
                    _("To pole jest wymagane dla aktywnej integracji."),
                )
            if not has_refresh_token or not has_cloud_id:
                self.add_error(
                    None,
                    _("Najpierw połącz konto firmy przez Dotykačka Connector."),
                )
        return cleaned

    def save(self):
        configuration = dict(self.connection.configuration)
        configuration.update(
            {
                "discount_group_id": self.cleaned_data.get("discount_group_id") or "",
            }
        )
        self.connection.configuration = configuration
        self.connection.enabled = self.cleaned_data["enabled"]
        self.connection.save()
        return self.connection


__all__ = ["DotykackaIntegrationForm"]
