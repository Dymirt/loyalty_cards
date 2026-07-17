"""Tenant portal query services."""

from dotykacka.models import IntegrationConnection, PhysicalCard


def portal_summary(tenant):
    return {
        "customer_count": tenant.customers.count(),
        "available_card_count": tenant.physical_cards.filter(
            status=PhysicalCard.Status.AVAILABLE,
            customer__isnull=True,
        ).count(),
        "assigned_card_count": tenant.physical_cards.filter(
            status=PhysicalCard.Status.ASSIGNED,
            customer__isnull=False,
        ).count(),
        "integration_statuses": {
            connection.provider: connection.enabled
            for connection in IntegrationConnection.objects.filter(tenant=tenant)
        },
    }
