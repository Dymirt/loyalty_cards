from django.contrib import admin

from .models import OperationalAlert, OperationalAlertEvent, RateLimitBucket, WorkerHeartbeat


class ReadOnlyOperationsAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(OperationalAlert)
class OperationalAlertAdmin(ReadOnlyOperationsAdmin):
    list_display = ("category", "severity", "status", "tenant", "last_seen_at")
    list_filter = ("category", "severity", "status")
    search_fields = ("fingerprint", "title", "source_id")


@admin.register(OperationalAlertEvent)
class OperationalAlertEventAdmin(ReadOnlyOperationsAdmin):
    list_display = ("alert", "kind", "actor", "created_at")
    list_filter = ("kind",)


@admin.register(WorkerHeartbeat)
class WorkerHeartbeatAdmin(ReadOnlyOperationsAdmin):
    list_display = ("worker_type", "worker_id", "status", "last_seen_at", "processed_count")
    list_filter = ("worker_type", "status")


@admin.register(RateLimitBucket)
class RateLimitBucketAdmin(ReadOnlyOperationsAdmin):
    list_display = ("scope", "window_started_at", "request_count", "limited_count")
    list_filter = ("scope",)
