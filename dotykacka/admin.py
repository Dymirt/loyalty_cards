"""Legacy/provider registrations plus Phase 5 owner-admin imports."""

from django.contrib import admin

# Importing the owner modules preserves the historical model registrations even
# though ``dotykacka`` is first in INSTALLED_APPS and is autodiscovered first.
import card_artwork.admin  # noqa: F401
import cards.admin  # noqa: F401
import customers.admin  # noqa: F401
import tenants.admin  # noqa: F401

from .models import AuditEvent, IntegrationConnection, WalletPass


@admin.register(IntegrationConnection)
class IntegrationConnectionAdmin(admin.ModelAdmin):
    list_display = ("tenant", "provider", "enabled", "secret_configured", "updated_at")
    list_filter = ("provider", "enabled")
    exclude = ("credentials_encrypted",)
    readonly_fields = ("last_error_code",)

    @admin.display(boolean=True, description="Secret configured")
    def secret_configured(self, obj):
        return bool(obj.credentials_encrypted)

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(WalletPass)
class WalletPassAdmin(admin.ModelAdmin):
    list_display = ("tenant", "customer", "apple_serial", "google_object_id")
    list_filter = ("tenant",)

    def has_delete_permission(self, request, obj=None):
        return False


admin.site.register(AuditEvent)
