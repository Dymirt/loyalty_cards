from django.contrib import admin

from .models import (
    Enrollment,
    EnrollmentAccessLink,
    EnrollmentEvent,
    EnrollmentFollowUp,
    VirtualCardApiKey,
    VirtualCardApplication,
    VirtualCardFollowUp,
)


class ReadOnlyEnrollmentAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Enrollment)
class EnrollmentAdmin(ReadOnlyEnrollmentAdmin):
    list_display = ("id", "tenant", "customer", "physical_card", "registered_at")
    list_filter = ("tenant", "source")
    search_fields = ("customer__klient_id", "physical_card__code", "registration_key")


@admin.register(EnrollmentFollowUp)
class EnrollmentFollowUpAdmin(ReadOnlyEnrollmentAdmin):
    list_display = ("id", "enrollment", "kind", "generation", "operation", "created_at")
    list_filter = ("kind", "operation")


@admin.register(EnrollmentEvent)
class EnrollmentEventAdmin(ReadOnlyEnrollmentAdmin):
    list_display = ("id", "enrollment", "kind", "actor", "created_at")
    list_filter = ("kind",)


@admin.register(EnrollmentAccessLink)
class EnrollmentAccessLinkAdmin(ReadOnlyEnrollmentAdmin):
    list_display = ("id", "enrollment", "purpose", "reason", "expires_at", "created_at")
    list_filter = ("purpose", "reason")


@admin.register(VirtualCardApiKey)
class VirtualCardApiKeyAdmin(ReadOnlyEnrollmentAdmin):
    list_display = ("name", "tenant", "token_prefix", "created_at", "last_used_at", "revoked_at")
    list_filter = ("tenant", "revoked_at")
    search_fields = ("name", "token_prefix", "tenant__name")


@admin.register(VirtualCardApplication)
class VirtualCardApplicationAdmin(ReadOnlyEnrollmentAdmin):
    list_display = ("public_id", "tenant", "customer", "physical_card", "source", "created_at")
    list_filter = ("tenant", "source", "card_design")
    search_fields = ("public_id", "customer__email", "customer__klient_id")


@admin.register(VirtualCardFollowUp)
class VirtualCardFollowUpAdmin(ReadOnlyEnrollmentAdmin):
    list_display = ("application", "kind", "integration_job", "created_at")
    list_filter = ("kind",)
