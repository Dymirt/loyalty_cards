from django.contrib import admin

from .models import DotykackaAccessToken, DotykackaConnectState


@admin.register(DotykackaConnectState)
class DotykackaConnectStateAdmin(admin.ModelAdmin):
    list_display = ("id", "tenant", "created_by", "expires_at", "used_at")
    readonly_fields = [field.name for field in DotykackaConnectState._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(DotykackaAccessToken)
class DotykackaAccessTokenAdmin(admin.ModelAdmin):
    list_display = ("id", "tenant", "cloud_id", "obtained_at", "expires_at", "invalidated_at")
    exclude = ("token_encrypted",)
    readonly_fields = [
        field.name
        for field in DotykackaAccessToken._meta.fields
        if field.name != "token_encrypted"
    ]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
