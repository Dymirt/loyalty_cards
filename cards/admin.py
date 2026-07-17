from django.contrib import admin

from .models import CardBatch, PhysicalCard


@admin.register(PhysicalCard)
class PhysicalCardAdmin(admin.ModelAdmin):
    list_display = ("code", "tenant", "status", "customer", "is_legacy")
    list_filter = ("tenant", "status", "is_legacy")
    search_fields = ("code",)

    def has_delete_permission(self, request, obj=None):
        return False


admin.site.register(CardBatch)
