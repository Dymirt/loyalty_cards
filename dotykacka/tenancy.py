"""Tenant lookup and authorization helpers."""

from django.conf import settings
from django.shortcuts import get_object_or_404

from .models import Tenant, TenantMembership


def get_default_tenant() -> Tenant:
    return Tenant.objects.select_related("brand").get(
        slug=settings.LEGACY_DEFAULT_TENANT_SLUG,
        is_active=True,
    )


def get_public_tenant(slug: str | None = None) -> Tenant:
    if slug is None:
        tenant = get_default_tenant()
        if not tenant.public_registration_enabled:
            raise Tenant.DoesNotExist
        return tenant
    return get_object_or_404(
        Tenant.objects.select_related("brand"),
        slug=slug,
        is_active=True,
        public_registration_enabled=True,
    )


def can_manage_integrations(user, tenant: Tenant) -> bool:
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return TenantMembership.objects.filter(
        tenant=tenant,
        user=user,
        role=TenantMembership.Role.OWNER,
        is_active=True,
    ).exists()
