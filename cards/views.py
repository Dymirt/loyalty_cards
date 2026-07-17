"""Card-inventory views retained ahead of the full printing extraction."""

from django.shortcuts import render

from tenants.authorization import superuser_required
from tenants.models import Tenant

from .services import tenant_inventory_queryset


@superuser_required
def platform_print_center(request):
    tenants = tenant_inventory_queryset(Tenant)
    return render(
        request,
        "cards/platform_print_center.html",
        {"tenants": tenants, "platform_nav": "print_center"},
    )
