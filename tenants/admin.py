from django.contrib import admin

from .models import Tenant, TenantBrand, TenantBrandRevision, TenantMembership


class ImmutableAdmin(admin.ModelAdmin):
    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return obj is None


@admin.register(TenantBrandRevision)
class TenantBrandRevisionAdmin(ImmutableAdmin):
    list_display = ("tenant", "version", "public_name", "created_at")
    list_filter = ("tenant",)


admin.site.register(Tenant)
admin.site.register(TenantMembership)
admin.site.register(TenantBrand)
