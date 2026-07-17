"""Customer listing views."""

import logging

from django.shortcuts import render

from tenants.authorization import get_default_tenant, superuser_required

from .services import list_legacy_provider_customers


logger = logging.getLogger(__name__)


@superuser_required
def get_all_customers(request):
    """Tenant-owned local listing; POS reconciliation runs through jobs."""

    tenant = get_default_tenant()
    all_customers = list_legacy_provider_customers(tenant)
    error = None
    return render(
        request,
        "customers/list.html",
        {
            "customers": all_customers,
            "error": error,
            "tenant": tenant,
            "active_nav": "customers",
        },
    )
