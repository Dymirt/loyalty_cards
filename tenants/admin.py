from django.contrib import admin

from .models import (
    Tenant,
    TenantBrand,
    TenantBrandRevision,
    TenantDomain,
    TenantMembership,
)


class ImmutableAdmin(admin.ModelAdmin):
    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return obj is None


@admin.register(TenantBrandRevision)
class TenantBrandRevisionAdmin(ImmutableAdmin):
    list_display = ("tenant", "version", "public_name", "created_at")
    list_filter = ("tenant",)


@admin.register(TenantDomain)
class TenantDomainAdmin(admin.ModelAdmin):
    list_display = ("hostname", "tenant", "status", "is_primary", "verified_at")
    list_filter = ("status", "is_primary")
    search_fields = ("hostname", "tenant__name")
    readonly_fields = (
        "tenant",
        "hostname",
        "primary_for_tenant",
        "created_by",
        "created_at",
        "updated_at",
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


admin.site.register(Tenant)
admin.site.register(TenantMembership)
admin.site.register(TenantBrand)
