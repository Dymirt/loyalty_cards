"""Transactional card-inventory application services."""

from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db.models import Count, Q
from django.utils.translation import gettext as _

from .models import PhysicalCard


CARD_IMAGE_FIELDS = {
    "front": "front_image_path",
    "back": "back_image_path",
}


def physical_card_asset_path(card, side):
    """Resolve a saved card image, following a virtual card's immutable source."""

    try:
        field_name = CARD_IMAGE_FIELDS[side]
    except KeyError as exc:
        raise ValidationError(_("Nieznana strona karty.")) from exc
    asset_card = card
    relative_path = getattr(asset_card, field_name, "")
    if not relative_path and card.artwork_source_id:
        asset_card = card.artwork_source
        relative_path = getattr(asset_card, field_name, "")
    if not relative_path:
        raise ValidationError(_("Karta nie ma zapisanego pliku %(side)s.") % {"side": side})
    media_root = Path(settings.MEDIA_ROOT).resolve()
    path = (media_root / relative_path).resolve()
    if media_root not in path.parents:
        raise ValidationError(_("Niedozwolona ścieżka pliku karty."))
    return path


def tenant_inventory_queryset(tenant_model):
    return tenant_model.objects.filter(is_active=True).annotate(
        customer_count=Count("customers", distinct=True),
        available_card_count=Count(
            "physical_cards",
            filter=Q(
                physical_cards__status=PhysicalCard.Status.AVAILABLE,
                physical_cards__customer__isnull=True,
                physical_cards__artwork_source__isnull=True,
            ),
            distinct=True,
        ),
        assigned_card_count=Count(
            "physical_cards",
            filter=Q(
                physical_cards__status=PhysicalCard.Status.ASSIGNED,
                physical_cards__customer__isnull=False,
                physical_cards__artwork_source__isnull=True,
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
        artwork_source__isnull=True,
    ).exists()
