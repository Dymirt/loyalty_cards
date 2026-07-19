"""Transactional card-inventory application services."""

from django.core.exceptions import ValidationError
from django.db.models import Count, Q
from django.utils.translation import gettext as _

from .models import PhysicalCard


def tenant_inventory_queryset(tenant_model):
    return tenant_model.objects.filter(is_active=True).annotate(
        customer_count=Count("customers", distinct=True),
        available_card_count=Count(
            "physical_cards",
            filter=Q(
                physical_cards__status=PhysicalCard.Status.AVAILABLE,
                physical_cards__customer__isnull=True,
            ),
            distinct=True,
        ),
        assigned_card_count=Count(
            "physical_cards",
            filter=Q(
                physical_cards__status=PhysicalCard.Status.ASSIGNED,
                physical_cards__customer__isnull=False,
            ),
            distinct=True,
        ),
    )


def lock_available_card(*, tenant, code):
    return PhysicalCard.objects.select_for_update().get(
        tenant=tenant,
        code=code,
        status=PhysicalCard.Status.AVAILABLE,
        customer__isnull=True,
    )


def assign_locked_card(*, card, customer):
    if card.tenant_id != customer.tenant_id:
        raise ValidationError(_("Karta i klient muszą należeć do tej samej firmy."))
    if card.customer_id or card.status != PhysicalCard.Status.AVAILABLE:
        raise ValidationError(_("Karta nie jest dostępna do przypisania."))
    card.customer = customer
    card.status = PhysicalCard.Status.ASSIGNED
    card.save(update_fields=["customer", "status"])
    return card


def card_is_available(*, tenant, code):
    return PhysicalCard.objects.filter(
        tenant=tenant,
        code=code,
        status=PhysicalCard.Status.AVAILABLE,
        customer__isnull=True,
    ).exists()
