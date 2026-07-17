from django.contrib import admin

from .models import (
    AuditEvent,
    CardBatch,
    IntegrationConnection,
    Klient,
    PhysicalCard,
    Tenant,
    TenantBrand,
    TenantMembership,
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


admin.site.register(Tenant)
admin.site.register(TenantMembership)
admin.site.register(TenantBrand)
admin.site.register(CardBatch)
admin.site.register(Klient)
admin.site.register(AuditEvent)
