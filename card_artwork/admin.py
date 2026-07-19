from django.contrib import admin

from .models import CardArtifact, CardArtworkSource, CardDesign, CropPlan


class ImmutableAdmin(admin.ModelAdmin):
    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return obj is None


@admin.register(CardDesign)
class CardDesignAdmin(ImmutableAdmin):
    list_display = ("tenant", "version", "name", "published_at")
    list_filter = ("tenant", "layout_preset", "crop_mode")


@admin.register(CardArtworkSource)
class CardArtworkSourceAdmin(ImmutableAdmin):
    list_display = ("tenant", "name", "width_px", "height_px", "created_at")
    list_filter = ("tenant",)


@admin.register(CardArtifact)
class CardArtifactAdmin(ImmutableAdmin):
    list_display = ("tenant", "design", "kind", "sha256", "created_at")
    list_filter = ("tenant", "kind")


@admin.register(CropPlan)
class CropPlanAdmin(ImmutableAdmin):
    list_display = ("tenant", "design", "card_code", "render_version", "created_at")
    list_filter = ("tenant", "render_version")
    search_fields = ("card_code", "source_sha256")
