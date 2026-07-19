from django.contrib import admin

from .models import CommunicationDelivery


@admin.register(CommunicationDelivery)
class CommunicationDeliveryAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "tenant",
        "customer",
        "channel",
        "generation",
        "status",
        "started_at",
    )
    list_filter = ("status", "channel", "tenant")
    search_fields = ("customer__klient_id", "integration_job__idempotency_key")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
