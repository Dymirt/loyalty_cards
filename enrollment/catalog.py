"""Virtual-card inventory backed by existing, immutable rendered artwork."""

from django.db import transaction
from django.db.models import Max

from cards.virtual import (
    VIRTUAL_CARD_ARTWORK_COUNT,
    VIRTUAL_CARD_FIRST_NUMBER,
    virtual_artwork_source_number,
)
from dotykacka.models import CardBatch, PhysicalCard, Tenant


VIRTUAL_CARD_DESIGN_LIMIT = 4


def _available_virtual_cards(tenant):
    return tenant.physical_cards.filter(
        number__gte=VIRTUAL_CARD_FIRST_NUMBER,
        artwork_source__isnull=False,
        status=PhysicalCard.Status.AVAILABLE,
        customer__isnull=True,
    )


@transaction.atomic
def ensure_virtual_card_pool(tenant, *, limit=VIRTUAL_CARD_DESIGN_LIMIT):
    """Keep four unique MB-601+ choices without rendering or copying artwork."""

    tenant = Tenant.objects.select_for_update().get(pk=tenant.pk)
    available_count = _available_virtual_cards(tenant).count()
    missing = max(0, limit - available_count)
    if not missing:
        return

    highest_number = (
        tenant.physical_cards.aggregate(highest=Max("number"))["highest"] or 0
    )
    next_number = max(VIRTUAL_CARD_FIRST_NUMBER - 1, highest_number) + 1
    batch = None
    while missing:
        source_number = virtual_artwork_source_number(next_number)
        source = (
            tenant.physical_cards.select_related("batch__design")
            .filter(
                number=source_number,
                artwork_source__isnull=True,
            )
            .exclude(front_image_path="")
            .exclude(back_image_path="")
            .first()
        )
        if source is None:
            break
        if batch is None:
            batch, _created = CardBatch.objects.get_or_create(
                tenant=tenant,
                name=f"Virtual Wallet {tenant.card_prefix}-601+",
                defaults={
                    "design": source.batch.design,
                    "card_prefix": tenant.card_prefix,
                    "start_number": VIRTUAL_CARD_FIRST_NUMBER,
                    "end_number": 2_147_483_647,
                    "status": CardBatch.Status.GENERATED,
                    "design_snapshot": {
                        "virtual_wallet": True,
                        "artwork_source_start": 1,
                        "artwork_source_end": VIRTUAL_CARD_ARTWORK_COUNT,
                        "asset_policy": "reuse_existing_files",
                    },
                },
            )
        card = PhysicalCard(
            tenant=tenant,
            batch=batch,
            artwork_source=source,
            code=f"{tenant.card_prefix}-{next_number}",
            number=next_number,
            status=PhysicalCard.Status.AVAILABLE,
        )
        card.full_clean()
        card.save()
        missing -= 1
        next_number += 1


def virtual_card_designs(tenant):
    """Return four unique MB-601+ cards backed by MB-1..600 artwork."""

    ensure_virtual_card_pool(tenant)

    card_ids = list(
        _available_virtual_cards(tenant)
        .order_by("number", "pk")
        .values_list("pk", flat=True)[:VIRTUAL_CARD_DESIGN_LIMIT]
    )
    return (
        tenant.physical_cards.filter(pk__in=card_ids)
        .select_related(
            "tenant",
            "batch__design__brand_revision",
            "artwork_source__batch__design__brand_revision",
        )
        .order_by("number", "pk")
    )


__all__ = [
    "VIRTUAL_CARD_ARTWORK_COUNT",
    "VIRTUAL_CARD_DESIGN_LIMIT",
    "VIRTUAL_CARD_FIRST_NUMBER",
    "ensure_virtual_card_pool",
    "virtual_artwork_source_number",
    "virtual_card_designs",
]
