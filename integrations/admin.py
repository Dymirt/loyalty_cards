from django.contrib import admin

from .models import IntegrationJob


@admin.register(IntegrationJob)
class IntegrationJobAdmin(admin.ModelAdmin):
    list_display = ("id", "tenant", "kind", "status", "attempts", "available_at")
    list_filter = ("status", "kind")
    search_fields = ("idempotency_key",)
    readonly_fields = (
        "tenant",
        "connection",
        "kind",
        "idempotency_key",
        "payload",
        "status",
        "attempts",
        "max_attempts",
        "available_at",
        "locked_at",
        "locked_by",
        "finished_at",
        "last_error_code",
        "created_at",
        "updated_at",
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
