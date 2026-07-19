from django.contrib import admin

from .models import Enrollment, EnrollmentAccessLink, EnrollmentEvent, EnrollmentFollowUp


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
