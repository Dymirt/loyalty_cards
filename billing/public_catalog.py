"""Read-only projections of commercial data approved for public marketing pages."""

from dataclasses import dataclass
from decimal import Decimal

from .models import CardPriceTier, PlanVersion, PriceBookVersion


@dataclass(frozen=True)
class PublicPlanOffer:
    name: str
    description: str
    version: int
    billing_interval: str
    billing_interval_label: str
    recurring_amount: Decimal
    currency: str
    tax_display: str
    tax_label: str
    active_seat_limit: int | None
    card_issuance_limit: int | None
    included_print_quantity: int
    print_overage_allowed: bool


@dataclass(frozen=True)
class PublicProductionTier:
    minimum_quantity: int
    maximum_quantity: int | None
    unit_amount: Decimal


@dataclass(frozen=True)
class PublicProductionPricing:
    name: str
    version: int
    currency: str
    tax_display: str
    tax_label: str
    shipping_amount: Decimal
    tiers: tuple[PublicProductionTier, ...]


def _tax_label(value):
    return {
        PlanVersion.TaxDisplay.INCLUSIVE: "cena brutto",
        PlanVersion.TaxDisplay.EXCLUSIVE: "cena netto, podatek doliczany",
        PlanVersion.TaxDisplay.NOT_APPLICABLE: "bez podatku",
    }[value]


def _interval_label(value):
    return {
        PlanVersion.BillingInterval.MONTHLY: "miesięcznie",
        PlanVersion.BillingInterval.YEARLY: "rocznie",
    }[value]


def published_plan_offers():
    """Return the highest published version of every active public plan."""

    rows = PlanVersion.objects.filter(
        plan__is_active=True,
        published_at__isnull=False,
        entitlement_policy__isnull=False,
    ).values(
        "plan_id",
        "plan__name",
        "plan__public_description",
        "version",
        "billing_interval",
        "recurring_amount",
        "currency",
        "tax_display",
        "entitlement_policy__active_seat_limit",
        "entitlement_policy__card_issuance_limit",
        "entitlement_policy__included_print_quantity",
        "entitlement_policy__print_overage_allowed",
    ).order_by("plan_id", "-version", "-pk")
    offers = []
    seen_plan_ids = set()
    for row in rows:
        if row["plan_id"] in seen_plan_ids:
            continue
        seen_plan_ids.add(row["plan_id"])
        offers.append(
            PublicPlanOffer(
                name=row["plan__name"],
                description=row["plan__public_description"],
                version=row["version"],
                billing_interval=row["billing_interval"],
                billing_interval_label=_interval_label(row["billing_interval"]),
                recurring_amount=row["recurring_amount"],
                currency=row["currency"],
                tax_display=row["tax_display"],
                tax_label=_tax_label(row["tax_display"]),
                active_seat_limit=row["entitlement_policy__active_seat_limit"],
                card_issuance_limit=row["entitlement_policy__card_issuance_limit"],
                included_print_quantity=row[
                    "entitlement_policy__included_print_quantity"
                ],
                print_overage_allowed=row[
                    "entitlement_policy__print_overage_allowed"
                ],
            )
        )
    return tuple(sorted(offers, key=lambda offer: (offer.recurring_amount, offer.name)))


def published_production_pricing():
    """Return the highest published version of every active production price book."""

    rows = list(
        PriceBookVersion.objects.filter(
            price_book__is_active=True,
            published_at__isnull=False,
        )
        .values(
            "id",
            "price_book_id",
            "price_book__name",
            "version",
            "currency",
            "tax_display",
            "shipping_amount",
        )
        .order_by("price_book_id", "-version", "-pk")
    )
    selected = []
    seen_price_books = set()
    for row in rows:
        if row["price_book_id"] in seen_price_books:
            continue
        seen_price_books.add(row["price_book_id"])
        selected.append(row)
    tiers_by_version = {row["id"]: [] for row in selected}
    if tiers_by_version:
        for tier in CardPriceTier.objects.filter(
            price_book_version_id__in=tiers_by_version
        ).values(
            "price_book_version_id",
            "minimum_quantity",
            "maximum_quantity",
            "unit_amount",
        ).order_by("price_book_version_id", "minimum_quantity"):
            tiers_by_version[tier["price_book_version_id"]].append(
                PublicProductionTier(
                    minimum_quantity=tier["minimum_quantity"],
                    maximum_quantity=tier["maximum_quantity"],
                    unit_amount=tier["unit_amount"],
                )
            )
    return tuple(
        PublicProductionPricing(
            name=row["price_book__name"],
            version=row["version"],
            currency=row["currency"],
            tax_display=row["tax_display"],
            tax_label=_tax_label(row["tax_display"]),
            shipping_amount=row["shipping_amount"],
            tiers=tuple(tiers_by_version[row["id"]]),
        )
        for row in selected
    )


def published_public_catalog():
    return {
        "public_plan_offers": published_plan_offers(),
        "public_production_pricing": published_production_pricing(),
    }


__all__ = [
    "PublicPlanOffer",
    "PublicProductionPricing",
    "PublicProductionTier",
    "published_plan_offers",
    "published_production_pricing",
    "published_public_catalog",
]
