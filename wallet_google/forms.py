"""Tenant opt-in for the platform-owned Google Wallet issuer."""

from django import forms

from integrations.models import IntegrationConnection
from tenants.forms import style_portal_form


class GoogleWalletIntegrationForm(forms.Form):
    enabled = forms.BooleanField(required=False, label="Włącz integrację")

    def __init__(self, *args, tenant, connection=None, **kwargs):
        self.tenant = tenant
        self.connection = connection or IntegrationConnection(
            tenant=tenant,
            provider=IntegrationConnection.Provider.GOOGLE_WALLET,
        )
        if not args and "data" not in kwargs:
            kwargs["initial"] = {"enabled": self.connection.enabled}
        super().__init__(*args, **kwargs)
        style_portal_form(self)

    def save(self):
        self.connection.enabled = self.cleaned_data["enabled"]
        # Preserve historical JSON byte-for-byte at the field level. Runtime
        # issuer/class identity is platform/tenant-derived and ignores it.
        self.connection.save(update_fields=("enabled", "updated_at"))
        return self.connection


__all__ = ["GoogleWalletIntegrationForm"]
