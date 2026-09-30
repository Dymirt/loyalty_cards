from django.contrib import admin
from django.db import transaction
from django.template.response import TemplateResponse

from dotykacka.models import AuditEvent, Tenant, TenantMembership

from .models import (
    ConsentRecord,
    Customer,
    CustomerExportApiToken,
    CustomerExternalIdentity,
)


def manageable_tenants(user):
    tenants = Tenant.objects.all()
    if user.is_superuser:
        return tenants
    return tenants.filter(
        memberships__user=user,
        memberships__role=TenantMembership.Role.OWNER,
        memberships__is_active=True,
    ).distinct()


class NoDeleteAdmin(admin.ModelAdmin):
    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ConsentRecord)
class ConsentRecordAdmin(NoDeleteAdmin):
    list_display = ("tenant", "customer", "purpose", "granted", "recorded_at")
    list_filter = ("tenant", "purpose", "granted")
    readonly_fields = (
        "tenant",
        "customer",
        "purpose",
        "policy_version",
        "consent_text",
        "consent_text_sha256",
        "granted",
        "source",
        "recorded_at",
        "revoked_at",
        "metadata",
    )

    def has_change_permission(self, request, obj=None):
        return obj is None


@admin.register(CustomerExternalIdentity)
class CustomerExternalIdentityAdmin(NoDeleteAdmin):
    list_display = (
        "tenant",
        "customer",
        "provider",
        "remote_id",
        "sync_status",
        "last_synced_at",
    )
    list_filter = ("tenant", "provider", "sync_status")


@admin.register(CustomerExportApiToken)
class CustomerExportApiTokenAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "tenant",
        "prefix_display",
        "status",
        "created_at",
        "last_used_at",
        "revoked_at",
    )
    list_filter = ("tenant", "revoked_at", "created_at")
    search_fields = ("name", "token_prefix", "tenant__name")
    ordering = ("-created_at", "-pk")
    actions = ("revoke_selected",)

    @admin.display(description="Prefiks tokenu")
    def prefix_display(self, obj):
        return f"{obj.token_prefix}…"

    @admin.display(boolean=True, description="Aktywny")
    def status(self, obj):
        return obj.is_active

    def _can_manage(self, request, obj=None):
        if not request.user.is_active or not request.user.is_staff:
            return False
        if request.user.is_superuser:
            return True
        tenants = manageable_tenants(request.user)
        if obj is None:
            return tenants.exists()
        return tenants.filter(pk=obj.tenant_id).exists()

    def has_module_permission(self, request):
        return self._can_manage(request)

    def has_view_permission(self, request, obj=None):
        return self._can_manage(request, obj)

    def has_add_permission(self, request):
        return self._can_manage(request)

    def has_change_permission(self, request, obj=None):
        return self._can_manage(request, obj)

    def has_delete_permission(self, request, obj=None):
        # Revocation preserves the audit trail and should be used instead.
        return False

    def get_queryset(self, request):
        queryset = super().get_queryset(request).select_related("tenant", "created_by")
        if request.user.is_superuser:
            return queryset
        return queryset.filter(tenant__in=manageable_tenants(request.user))

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "tenant":
            kwargs["queryset"] = manageable_tenants(request.user)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def get_fields(self, request, obj=None):
        if obj is None:
            return ("tenant", "name")
        return (
            "tenant",
            "name",
            "token_prefix",
            "created_by",
            "created_at",
            "last_used_at",
            "revoked_at",
        )

    def get_readonly_fields(self, request, obj=None):
        if obj is None:
            return ()
        return self.get_fields(request, obj)

    def save_model(self, request, obj, form, change):
        if not change:
            raw_token, obj.token_prefix, obj.token_hash = (
                CustomerExportApiToken.generate_credentials()
            )
            obj.created_by = request.user
            request._new_customer_export_api_token = raw_token
        super().save_model(request, obj, form, change)
        if not change:
            AuditEvent.objects.create(
                tenant=obj.tenant,
                actor=request.user,
                action="customer_export_api_token.created",
                object_type="customers.CustomerExportApiToken",
                object_id=str(obj.pk),
                metadata={"name": obj.name, "token_prefix": obj.token_prefix},
            )

    def response_add(self, request, obj, post_url_continue=None):
        raw_token = getattr(request, "_new_customer_export_api_token", None)
        if raw_token is None:
            return super().response_add(request, obj, post_url_continue)
        context = {
            **self.admin_site.each_context(request),
            "title": "Token API został utworzony",
            "opts": self.model._meta,
            "original": obj,
            "raw_token": raw_token,
        }
        return TemplateResponse(
            request,
            "admin/customers/customerexportapitoken/token_created.html",
            context,
        )

    @admin.action(description="Unieważnij wybrane aktywne tokeny")
    def revoke_selected(self, request, queryset):
        revoked = 0
        with transaction.atomic():
            for token in queryset.filter(revoked_at__isnull=True).select_related("tenant"):
                token.revoke()
                AuditEvent.objects.create(
                    tenant=token.tenant,
                    actor=request.user,
                    action="customer_export_api_token.revoked",
                    object_type="customers.CustomerExportApiToken",
                    object_id=str(token.pk),
                    metadata={"name": token.name, "token_prefix": token.token_prefix},
                )
                revoked += 1
        self.message_user(request, f"Unieważniono tokeny: {revoked}.")


admin.site.register(Customer)
