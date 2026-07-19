from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from billing.models import (
    CardPriceTier,
    EntitlementPolicy,
    Plan,
    PlanVersion,
    PriceBook,
    PriceBookVersion,
    TenantSubscription,
)
from billing.services import (
    accept_quote,
    create_print_quote,
    publish_plan_version,
    publish_price_book_version,
)
from card_artwork.services import generate_proof_artifacts
from dotykacka.tests.base import create_tenant_owner
from dotykacka.tests.test_card_designs import create_design


def create_commercial_setup(tenant, *, included_prints=0, unit_amount="5.00"):
    plan = Plan.objects.create(code=f"plan-{tenant.slug}", name=f"Plan {tenant.slug}")
    version = PlanVersion.objects.create(
        plan=plan,
        version=1,
        recurring_amount=Decimal("100.00"),
        currency="PLN",
        tax_display=PlanVersion.TaxDisplay.NOT_APPLICABLE,
    )
    EntitlementPolicy.objects.create(
        plan_version=version,
        included_print_quantity=included_prints,
        print_overage_allowed=True,
    )
    publish_plan_version(plan_version=version)
    TenantSubscription.objects.create(
        tenant=tenant,
        plan_version=version,
        status=TenantSubscription.Status.ACTIVE,
        starts_at=timezone.now() - timedelta(days=1),
    )
    book = PriceBook.objects.create(
        code=f"prices-{tenant.slug}",
        name=f"Prices {tenant.slug}",
    )
    price = PriceBookVersion.objects.create(
        price_book=book,
        version=1,
        currency="PLN",
        tax_display=PlanVersion.TaxDisplay.NOT_APPLICABLE,
        shipping_amount=Decimal("10.00"),
    )
    CardPriceTier.objects.create(
        price_book_version=price,
        minimum_quantity=1,
        maximum_quantity=None,
        unit_amount=Decimal(unit_amount),
    )
    publish_price_book_version(price_book_version=price)
    return price


def create_accepted_quote(tenant, price, *, quantity=2, key="quote-1", actor=None):
    quote, _ = create_print_quote(
        tenant=tenant,
        quantity=quantity,
        price_book_version=price,
        idempotency_key=key,
        actor=actor,
    )
    accept_quote(quote=quote)
    quote.refresh_from_db()
    return quote


def create_request_inputs(tenant, *, quantity=2, key="quote-1", actor=None):
    actor = actor or create_tenant_owner(tenant)
    design = create_design(tenant)
    generate_proof_artifacts(design=design)
    price = create_commercial_setup(tenant)
    quote = create_accepted_quote(
        tenant,
        price,
        quantity=quantity,
        key=key,
        actor=actor,
    )
    return actor, design, price, quote


def delivery_values():
    return {
        "delivery_name": "Synthetic Café",
        "delivery_address_line1": "Testowa 1",
        "delivery_address_line2": "",
        "delivery_postal_code": "00-001",
        "delivery_city": "Warszawa",
        "delivery_country": "PL",
        "notes": "Synthetic print test",
    }
