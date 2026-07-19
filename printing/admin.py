"""Read-oriented administration for centralized printing records."""

from django.contrib import admin

from .models import (
    FulfillmentEvent,
    PrintJob,
    PrintPackage,
    PrintRequest,
    PrintRequestEvent,
    PrintRun,
    PrintRunCard,
)


class NoDeleteAdmin(admin.ModelAdmin):
    def has_delete_permission(self, request, obj=None):
        return False


class ReadOnlyHistoryAdmin(NoDeleteAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(PrintRequest)
class PrintRequestAdmin(ReadOnlyHistoryAdmin):
    list_display = ("id", "tenant", "quantity", "status", "submitted_at")
    list_filter = ("status", "tenant")
    search_fields = ("idempotency_key", "tenant__name", "proof_checksum")
    readonly_fields = ("submitted_at", "updated_at", "snapshot", "proof_checksum")


@admin.register(PrintRun)
class PrintRunAdmin(ReadOnlyHistoryAdmin):
    list_display = ("id", "tenant", "quantity", "status", "start_number", "end_number")
    list_filter = ("status", "tenant")
    readonly_fields = ("layout_snapshot", "design_snapshot", "quote_snapshot")


@admin.register(PrintJob)
class PrintJobAdmin(ReadOnlyHistoryAdmin):
    list_display = ("id", "print_run", "status", "attempts", "available_at")
    list_filter = ("status",)
    readonly_fields = ("idempotency_key", "last_error_code", "created_at", "updated_at")


@admin.register(PrintPackage)
class PrintPackageAdmin(ReadOnlyHistoryAdmin):
    list_display = ("id", "print_run", "sha256", "size_bytes", "validated_at")
    readonly_fields = ("storage_key", "storage_path", "sha256", "size_bytes", "manifest")


@admin.register(FulfillmentEvent)
class FulfillmentEventAdmin(ReadOnlyHistoryAdmin):
    list_display = ("id", "tenant", "event_type", "print_request", "physical_card", "occurred_at")
    list_filter = ("event_type", "tenant")
    readonly_fields = ("idempotency_key", "metadata", "created_at")


admin.site.register(PrintRequestEvent, ReadOnlyHistoryAdmin)
admin.site.register(PrintRunCard, ReadOnlyHistoryAdmin)
