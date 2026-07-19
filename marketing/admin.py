from django.contrib import admin

from .models import MarketingLead


@admin.register(MarketingLead)
class MarketingLeadAdmin(admin.ModelAdmin):
    list_display = ("created_at", "company_name", "full_name", "email")
    search_fields = ("company_name", "full_name", "email")
    readonly_fields = (
        "public_id",
        "full_name",
        "company_name",
        "email",
        "phone",
        "message",
        "privacy_policy_version",
        "privacy_text_sha256",
        "content_sha256",
        "source_path",
        "created_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
