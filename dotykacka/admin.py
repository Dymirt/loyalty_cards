from django.contrib import admin

from .models import (
    AuditEvent,
    CardArtifact,
    CardBatch,
    CardDesign,
    IntegrationConnection,
    Klient,
    PhysicalCard,
    Tenant,
    TenantBrand,
    TenantBrandRevision,
    TenantMembership,
    WalletPass,
)


@admin.register(IntegrationConnection)
class IntegrationConnectionAdmin(admin.ModelAdmin):
    list_display = (
        "tenant",
        "provider",
        "enabled",
        "secret_configured",
        "updated_at",
    )
    list_filter = ("provider", "enabled")
    exclude = ("credentials_encrypted",)
    readonly_fields = ("last_error_code",)

    @admin.display(boolean=True, description="Secret configured")
    def secret_configured(self, obj):
        return bool(obj.credentials_encrypted)

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(PhysicalCard)
class PhysicalCardAdmin(admin.ModelAdmin):
    list_display = ("code", "tenant", "status", "customer", "is_legacy")
    list_filter = ("tenant", "status", "is_legacy")
    search_fields = ("code",)

    def has_delete_permission(self, request, obj=None):
        return False


class ImmutableAdmin(admin.ModelAdmin):
    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return obj is None


@admin.register(CardDesign)
class CardDesignAdmin(ImmutableAdmin):
    list_display = ("tenant", "version", "name", "published_at")
    list_filter = ("tenant", "layout_preset", "crop_mode")


@admin.register(TenantBrandRevision)
class TenantBrandRevisionAdmin(ImmutableAdmin):
    list_display = ("tenant", "version", "public_name", "created_at")
    list_filter = ("tenant",)


@admin.register(CardArtifact)
class CardArtifactAdmin(ImmutableAdmin):
    list_display = ("tenant", "design", "kind", "sha256", "created_at")
    list_filter = ("tenant", "kind")


@admin.register(WalletPass)
class WalletPassAdmin(admin.ModelAdmin):
    list_display = ("tenant", "customer", "apple_serial", "google_object_id")
    list_filter = ("tenant",)

    def has_delete_permission(self, request, obj=None):
        return False


admin.site.register(Tenant)
admin.site.register(TenantMembership)
admin.site.register(TenantBrand)
admin.site.register(CardBatch)
admin.site.register(Klient)
admin.site.register(AuditEvent)
