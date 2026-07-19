"""Tenant portal views."""

from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, render

from .authorization import (
    can_access_tenant,
    can_manage_billing,
    can_manage_card_designs,
    can_manage_integrations,
)
from .models import Tenant
from .services import portal_summary


@login_required
def tenant_portal(request, tenant_slug):
    tenant = get_object_or_404(
        Tenant.objects.select_related("brand"),
        slug=tenant_slug,
        is_active=True,
    )
    if not can_access_tenant(request.user, tenant):
        return HttpResponseForbidden("Nie masz dostępu do tej firmy.")

    summary = portal_summary(tenant)
    return render(
        request,
        "tenants/portal.html",
        {
            "tenant": tenant,
            "active_nav": "overview",
            "can_manage_integrations": can_manage_integrations(request.user, tenant),
            "can_manage_card_designs": can_manage_card_designs(request.user, tenant),
            "can_manage_billing": can_manage_billing(request.user, tenant),
            "can_manage_printing": can_manage_billing(request.user, tenant),
            **summary,
        },
    )
