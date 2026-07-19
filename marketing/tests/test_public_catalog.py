from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from billing.models import (
    CardPriceTier,
    EntitlementPolicy,
    Plan,
    PlanVersion,
    PriceBook,
    PriceBookVersion,
)
from billing.public_catalog import published_public_catalog
from billing.services import publish_plan_version, publish_price_book_version


def create_plan_version(
    plan,
    *,
    version,
    amount,
    published=False,
    seats=3,
    issuances=250,
    included_prints=25,
):
    item = PlanVersion.objects.create(
        plan=plan,
        version=version,
        recurring_amount=Decimal(amount),
        currency="PLN",
        billing_interval=PlanVersion.BillingInterval.MONTHLY,
        tax_display=PlanVersion.TaxDisplay.INCLUSIVE,
    )
    EntitlementPolicy.objects.create(
        plan_version=item,
        active_seat_limit=seats,
        card_issuance_limit=issuances,
        included_print_quantity=included_prints,
        print_overage_allowed=True,
    )
    if published:
        publish_plan_version(plan_version=item)
    return item


def create_price_version(price_book, *, version, amount, published=False):
    item = PriceBookVersion.objects.create(
        price_book=price_book,
        version=version,
        currency="PLN",
        tax_display=PlanVersion.TaxDisplay.INCLUSIVE,
        shipping_amount=Decimal("15.00"),
    )
    CardPriceTier.objects.create(
        price_book_version=item,
        minimum_quantity=1,
        maximum_quantity=99,
        unit_amount=Decimal(amount),
    )
    CardPriceTier.objects.create(
        price_book_version=item,
        minimum_quantity=100,
        maximum_quantity=None,
        unit_amount=Decimal("3.80"),
    )
    if published:
        publish_price_book_version(price_book_version=item)
    return item


class PublicCatalogTests(TestCase):
    def test_only_latest_published_versions_of_active_catalog_are_returned(self):
        public_plan = Plan.objects.create(
            code="public-plan",
            name="Plan Publiczny",
            public_description="Opis zatwierdzonego planu.",
        )
        create_plan_version(public_plan, version=1, amount="99.00", published=True)
        create_plan_version(public_plan, version=2, amount="1.00", published=False)
        inactive_plan = Plan.objects.create(
            code="internal-plan",
            name="Plan Wewnętrzny",
            is_active=False,
        )
        create_plan_version(inactive_plan, version=1, amount="777.00", published=True)

        public_prices = PriceBook.objects.create(code="public-production", name="Druk kart")
        create_price_version(public_prices, version=1, amount="4.50", published=True)
        create_price_version(public_prices, version=2, amount="1.00", published=False)
        internal_prices = PriceBook.objects.create(
            code="internal-production",
            name="Ceny wewnętrzne",
            is_active=False,
        )
        create_price_version(internal_prices, version=1, amount="0.10", published=True)

        before = {
            "plans": PlanVersion.objects.count(),
            "prices": PriceBookVersion.objects.count(),
        }
        catalog = published_public_catalog()

        self.assertEqual(len(catalog["public_plan_offers"]), 1)
        offer = catalog["public_plan_offers"][0]
        self.assertEqual(offer.name, "Plan Publiczny")
        self.assertEqual(offer.version, 1)
        self.assertEqual(offer.recurring_amount, Decimal("99.00"))
        self.assertEqual(offer.active_seat_limit, 3)
        self.assertEqual(offer.card_issuance_limit, 250)
        self.assertEqual(offer.included_print_quantity, 25)
        self.assertEqual(len(catalog["public_production_pricing"]), 1)
        production = catalog["public_production_pricing"][0]
        self.assertEqual(production.name, "Druk kart")
        self.assertEqual(production.version, 1)
        self.assertEqual(production.tiers[0].unit_amount, Decimal("4.50"))
        self.assertEqual(production.tiers[1].minimum_quantity, 100)
        response = self.client.get(reverse("marketing:pricing"))
        self.assertContains(response, "Plan Publiczny")
        self.assertContains(response, "Druk kart")
        self.assertNotContains(response, "Plan Wewnętrzny")
        self.assertNotContains(response, "Ceny wewnętrzne")
        self.assertEqual(
            response.context["public_plan_offers"][0].recurring_amount,
            Decimal("99.00"),
        )
        self.assertEqual(
            before,
            {
                "plans": PlanVersion.objects.count(),
                "prices": PriceBookVersion.objects.count(),
            },
        )
