from django.contrib import admin

from .models import ConsentRecord, Customer, CustomerExternalIdentity


class NoDeleteAdmin(admin.ModelAdmin):
    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ConsentRecord)
class ConsentRecordAdmin(NoDeleteAdmin):
    list_display = ("tenant", "customer", "purpose", "granted", "recorded_at")
    list_filter = ("tenant", "purpose", "granted")
    readonly_fields = (
        "tenant",
        "customer",
        "purpose",
        "policy_version",
        "consent_text",
        "consent_text_sha256",
        "granted",
        "source",
        "recorded_at",
        "revoked_at",
        "metadata",
    )

    def has_change_permission(self, request, obj=None):
        return obj is None


@admin.register(CustomerExternalIdentity)
class CustomerExternalIdentityAdmin(NoDeleteAdmin):
    list_display = (
        "tenant",
        "customer",
        "provider",
        "remote_id",
        "sync_status",
        "last_synced_at",
    )
    list_filter = ("tenant", "provider", "sync_status")


admin.site.register(Customer)
