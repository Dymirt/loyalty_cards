"""Published virtual-card design catalog rules."""


VIRTUAL_CARD_DESIGN_LIMIT = 4


def virtual_card_designs(tenant):
    """Return the four newest designs that can be selected for a new card."""

    catalog = tenant.card_designs.filter(is_virtual_catalog=True)
    if not catalog.exists():
        catalog = tenant.card_designs.all()
    design_ids = list(
        catalog.order_by("-version", "-pk").values_list(
            "pk", flat=True
        )[:VIRTUAL_CARD_DESIGN_LIMIT]
    )
    return tenant.card_designs.filter(pk__in=design_ids).select_related(
        "brand_revision", "tenant"
    ).order_by("-version", "-pk")


__all__ = ["VIRTUAL_CARD_DESIGN_LIMIT", "virtual_card_designs"]
