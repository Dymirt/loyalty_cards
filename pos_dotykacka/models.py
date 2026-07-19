"""Additive state for Dotykačka Connector v2 and encrypted token caching."""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

from integrations.secrets import decrypt_credentials, encrypt_credentials


class DotykackaConnectState(models.Model):
    tenant = models.ForeignKey(
        "dotykacka.Tenant",
        on_delete=models.PROTECT,
        related_name="dotykacka_connect_states",
    )
    connection = models.ForeignKey(
        "dotykacka.IntegrationConnection",
        on_delete=models.PROTECT,
        related_name="connector_states",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="dotykacka_connect_states",
    )
    state_digest = models.CharField(max_length=64, unique=True)
    session_digest = models.CharField(max_length=64)
    redirect_uri = models.URLField(max_length=700)
    expires_at = models.DateTimeField(db_index=True)
    used_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def clean(self):
        if self.connection_id and self.connection.tenant_id != self.tenant_id:
            raise ValidationError(
                {"connection": _("Stan Connectora i połączenie muszą należeć do tej samej firmy.")}
            )

    def delete(self, *args, **kwargs):
        raise ValidationError(_("Historii stanu Connectora nie można usuwać."))


class DotykackaAccessToken(models.Model):
    tenant = models.ForeignKey(
        "dotykacka.Tenant",
        on_delete=models.PROTECT,
        related_name="dotykacka_access_tokens",
    )
    connection = models.ForeignKey(
        "dotykacka.IntegrationConnection",
        on_delete=models.PROTECT,
        related_name="encrypted_access_tokens",
    )
    cloud_id = models.CharField(max_length=100)
    token_encrypted = models.TextField()
    obtained_at = models.DateTimeField()
    expires_at = models.DateTimeField(db_index=True)
    invalidated_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(
                fields=("connection", "cloud_id", "expires_at"),
                name="dotykacka_token_lookup_idx",
            )
        ]
        ordering = ("-obtained_at", "-pk")

    def clean(self):
        if self.connection_id and self.connection.tenant_id != self.tenant_id:
            raise ValidationError(
                {"connection": _("Token dostępu i połączenie muszą należeć do tej samej firmy.")}
            )

    def set_token(self, token):
        self.token_encrypted = encrypt_credentials({"access_token": token})

    def get_token(self):
        return decrypt_credentials(self.token_encrypted).get("access_token", "")

    def delete(self, *args, **kwargs):
        raise ValidationError(_("Historii tokenów dostępu nie można usuwać."))


__all__ = ["DotykackaAccessToken", "DotykackaConnectState"]
