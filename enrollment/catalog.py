"""Available pre-rendered card catalog rules."""


VIRTUAL_CARD_DESIGN_LIMIT = 4


def virtual_card_designs(tenant):
    """Return four unassigned, already-rendered MB-* cards."""

    card_ids = list(
        tenant.physical_cards.filter(
            status="available",
            customer__isnull=True,
        )
        .order_by("number", "pk")
        .values_list("pk", flat=True)[:VIRTUAL_CARD_DESIGN_LIMIT]
    )
    return (
        tenant.physical_cards.filter(pk__in=card_ids)
        .select_related("tenant", "batch__design__brand_revision")
        .order_by("number", "pk")
    )


__all__ = ["VIRTUAL_CARD_DESIGN_LIMIT", "virtual_card_designs"]
