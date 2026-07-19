"""Tenant lookup and authorization services."""

import re

from django.conf import settings
from django.contrib.auth.decorators import user_passes_test
from django.shortcuts import get_object_or_404

from .models import Tenant, TenantDomain, TenantMembership


superuser_required = user_passes_test(
    lambda user: user.is_active and user.is_superuser,
    login_url="/admin/login/",
)


def get_default_tenant() -> Tenant:
    return Tenant.objects.select_related("brand").get(
        slug=settings.LEGACY_DEFAULT_TENANT_SLUG,
        is_active=True,
    )


def tenant_for_verified_host(host: str | None):
    hostname = (host or "").strip().lower().rstrip(".")
    if ":" in hostname:
        hostname = hostname.split(":", 1)[0]
    if not hostname:
        return None
    domain = (
        TenantDomain.objects.select_related("tenant__brand")
        .filter(
            hostname=hostname,
            status=TenantDomain.Status.VERIFIED,
            tenant__is_active=True,
            tenant__public_registration_enabled=True,
        )
        .order_by("-is_primary", "pk")
        .first()
    )
    return domain.tenant if domain else None


def tenant_for_card_code(raw_code: str | None):
    """Resolve the public tenant from a globally unique physical-card prefix."""

    value = str(raw_code or "").strip().upper()
    match = re.fullmatch(r"(?P<prefix>[A-Z][A-Z0-9]{0,9})-[1-9][0-9]*", value)
    if not match:
        return None
    return (
        Tenant.objects.select_related("brand")
        .filter(
            card_prefix=match.group("prefix"),
            is_active=True,
            public_registration_enabled=True,
        )
        .first()
    )


def get_public_tenant(slug: str | None = None, *, host: str | None = None) -> Tenant:
    if slug is None:
        hosted_tenant = tenant_for_verified_host(host)
        if hosted_tenant is not None:
            return hosted_tenant
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


def can_manage_card_designs(user, tenant: Tenant) -> bool:
    return can_manage_integrations(user, tenant)


def can_manage_billing(user, tenant: Tenant) -> bool:
    return can_manage_integrations(user, tenant)


def can_access_tenant(user, tenant: Tenant) -> bool:
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return TenantMembership.objects.filter(
        tenant=tenant,
        user=user,
        is_active=True,
    ).exists()
