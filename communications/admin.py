from django.contrib import admin

from .models import (
    CampaignAsset,
    CampaignRecipient,
    CommunicationDelivery,
    EmailCampaign,
)


class ReadOnlyCommunicationAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


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


@admin.register(EmailCampaign)
class EmailCampaignAdmin(ReadOnlyCommunicationAdmin):
    list_display = (
        "name",
        "tenant",
        "status",
        "scheduled_for",
        "recipient_count",
        "sent_count",
        "failed_count",
    )
    list_filter = ("status", "generation_source", "tenant")
    search_fields = ("name", "subject", "goal")


@admin.register(CampaignRecipient)
class CampaignRecipientAdmin(ReadOnlyCommunicationAdmin):
    list_display = ("campaign", "customer", "status", "sent_at")
    list_filter = ("status", "tenant")
    search_fields = ("campaign__name", "email_snapshot", "customer__klient_id")


@admin.register(CampaignAsset)
class CampaignAssetAdmin(ReadOnlyCommunicationAdmin):
    list_display = ("original_name", "campaign", "tenant", "created_at")
    list_filter = ("tenant",)
