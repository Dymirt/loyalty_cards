from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import close_old_connections
from django.test import TestCase, TransactionTestCase, skipUnlessDBFeature
from django.utils import timezone

from tenants.models import Tenant, TenantMembership

from billing.models import (
    CardPack,
    CardPriceTier,
    EntitlementPolicy,
    Plan,
    PlanVersion,
    PriceBook,
    PriceBookVersion,
    PrintQuoteConsumption,
    Quote,
    TenantSubscription,
    UsageEvent,
)
from billing.services import (
    EntitlementLimitError,
    accept_quote,
    create_print_quote,
    consume_print_quote,
    ensure_active_seat_available,
    publish_plan_version,
    publish_price_book_version,
    record_card_issuance,
)


def create_tenant(slug):
    return Tenant.objects.create(
        name=slug.title(),
        slug=slug,
        card_prefix=slug[:2].upper(),
    )


def create_subscription(tenant, *, seats=2, issuance_limit=10, included_prints=0):
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
        active_seat_limit=seats,
        card_issuance_limit=issuance_limit,
        included_print_quantity=included_prints,
        print_overage_allowed=True,
    )
    publish_plan_version(plan_version=version)
    return TenantSubscription.objects.create(
        tenant=tenant,
        plan_version=version,
        status=TenantSubscription.Status.ACTIVE,
        starts_at=timezone.now() - timedelta(days=2),
    )


def create_price_version(*, code, version=1, tiers=((1, None, "5.00"),), shipping="0.00"):
    price_book, _ = PriceBook.objects.get_or_create(code=code, defaults={"name": code.title()})
    price_version = PriceBookVersion.objects.create(
        price_book=price_book,
        version=version,
        currency="PLN",
        tax_display=PlanVersion.TaxDisplay.NOT_APPLICABLE,
        shipping_amount=Decimal(shipping),
    )
    for minimum, maximum, amount in tiers:
        CardPriceTier.objects.create(
            price_book_version=price_version,
            minimum_quantity=minimum,
            maximum_quantity=maximum,
            unit_amount=Decimal(amount),
        )
    publish_price_book_version(price_book_version=price_version)
    return price_version


class EntitlementAndUsageTests(TestCase):
    def test_retry_creates_one_usage_event_and_limits_are_tenant_isolated(self):
        tenant_a = create_tenant("alpha")
        tenant_b = create_tenant("bravo")
        create_subscription(tenant_a, issuance_limit=1)
        create_subscription(tenant_b, issuance_limit=1)

        first = record_card_issuance(tenant=tenant_a, card_identity=17)
        retry = record_card_issuance(tenant=tenant_a, card_identity=17)

        self.assertTrue(first.created)
        self.assertFalse(retry.created)
        self.assertEqual(first.event.pk, retry.event.pk)
        self.assertEqual(UsageEvent.objects.filter(tenant=tenant_a).count(), 1)
        with self.assertRaises(EntitlementLimitError):
            record_card_issuance(tenant=tenant_a, card_identity=18)
        self.assertTrue(
            record_card_issuance(tenant=tenant_b, card_identity=18).created
        )

    def test_active_seat_is_active_membership_and_existing_users_are_not_deactivated(self):
        tenant = create_tenant("seats")
        create_subscription(tenant, seats=1)
        user = get_user_model().objects.create_user("owner")
        membership = TenantMembership.objects.create(
            tenant=tenant,
            user=user,
            role=TenantMembership.Role.OWNER,
            is_active=True,
        )

        ensure_active_seat_available(tenant=tenant, membership=membership)
        with self.assertRaises(EntitlementLimitError):
            ensure_active_seat_available(tenant=tenant)
        second_user = get_user_model().objects.create_user("second")
        with self.assertRaises(EntitlementLimitError):
            TenantMembership.objects.create(
                tenant=tenant,
                user=second_user,
                is_active=True,
            )

        membership.refresh_from_db()
        self.assertTrue(membership.is_active)
        self.assertFalse(
            TenantMembership.objects.filter(tenant=tenant, user=second_user).exists()
        )

    def test_tenant_without_subscription_is_explicitly_unmanaged(self):
        tenant = create_tenant("legacy")

        result = record_card_issuance(tenant=tenant, card_identity=1)

        self.assertFalse(result.managed)
        self.assertEqual(UsageEvent.objects.count(), 0)


class QuoteBoundaryTests(TestCase):
    def test_print_consumption_converts_reservation_once_without_double_counting(self):
        tenant = create_tenant("consumption")
        create_subscription(tenant, included_prints=10)
        price = create_price_version(code="consumption-prices")
        quote, _ = create_print_quote(
            tenant=tenant,
            quantity=6,
            price_book_version=price,
            idempotency_key="consume-6",
        )
        accept_quote(quote=quote)

        first, created = consume_print_quote(
            quote=quote,
            reference_type="PrintRun",
            reference_id="17",
        )
        retry, retry_created = consume_print_quote(
            quote=quote,
            reference_type="PrintRun",
            reference_id="17",
        )
        next_quote, _ = create_print_quote(
            tenant=tenant,
            quantity=4,
            price_book_version=price,
            idempotency_key="remaining-4",
        )

        self.assertTrue(created)
        self.assertFalse(retry_created)
        self.assertEqual(first.pk, retry.pk)
        self.assertEqual(PrintQuoteConsumption.objects.count(), 1)
        self.assertEqual(next_quote.included_quantity, 4)
        self.assertEqual(next_quote.billable_quantity, 0)

    def test_included_boundary_then_one_card_overage(self):
        tenant = create_tenant("included")
        create_subscription(tenant, included_prints=10)
        price = create_price_version(code="included-prices", shipping="10.00")

        included, _ = create_print_quote(
            tenant=tenant,
            quantity=10,
            price_book_version=price,
            idempotency_key="included-10",
        )
        self.assertEqual(included.included_quantity, 10)
        self.assertEqual(included.billable_quantity, 0)
        self.assertEqual(included.total_amount, Decimal("10.00"))
        accept_quote(quote=included)

        overage, _ = create_print_quote(
            tenant=tenant,
            quantity=1,
            price_book_version=price,
            idempotency_key="overage-1",
        )
        self.assertEqual(overage.included_quantity, 0)
        self.assertEqual(overage.billable_quantity, 1)
        self.assertEqual(overage.subtotal_amount, Decimal("5.00"))
        self.assertEqual(overage.total_amount, Decimal("15.00"))

    def test_acceptance_cannot_double_reserve_included_allowance(self):
        tenant = create_tenant("allowance-lock")
        create_subscription(tenant, included_prints=10)
        price = create_price_version(code="allowance-lock-prices")
        first, _ = create_print_quote(
            tenant=tenant,
            quantity=10,
            price_book_version=price,
            idempotency_key="allowance-first",
        )
        second, _ = create_print_quote(
            tenant=tenant,
            quantity=10,
            price_book_version=price,
            idempotency_key="allowance-second",
        )

        accept_quote(quote=first)
        with self.assertRaises(EntitlementLimitError):
            accept_quote(quote=second)

        second.refresh_from_db()
        self.assertEqual(second.status, Quote.Status.DRAFT)

    def test_per_card_tier_edge_is_deterministic(self):
        tenant = create_tenant("tiers")
        create_subscription(tenant)
        price = create_price_version(
            code="tier-prices",
            tiers=((1, 9, "5.00"), (10, None, "4.00")),
        )

        below, _ = create_print_quote(
            tenant=tenant,
            quantity=9,
            price_book_version=price,
            idempotency_key="tier-9",
        )
        edge, _ = create_print_quote(
            tenant=tenant,
            quantity=10,
            price_book_version=price,
            idempotency_key="tier-10",
        )

        self.assertEqual(below.subtotal_amount, Decimal("45.00"))
        self.assertEqual(edge.subtotal_amount, Decimal("40.00"))
        self.assertEqual(edge.snapshot["tier"]["minimum_quantity"], 10)

    def test_100_card_pack_boundary_reserves_on_acceptance(self):
        tenant = create_tenant("packs")
        create_subscription(tenant)
        price = create_price_version(code="pack-prices")
        pack = CardPack.objects.create(
            tenant=tenant,
            price_book_version=price,
            name="100 cards",
            purchased_quantity=100,
            purchase_amount=Decimal("300.00"),
            currency="PLN",
        )

        covered, _ = create_print_quote(
            tenant=tenant,
            quantity=100,
            price_book_version=price,
            idempotency_key="pack-100",
        )
        self.assertEqual(covered.pack_quantity, 100)
        self.assertEqual(covered.billable_quantity, 0)
        accept_quote(quote=covered)
        self.assertEqual(pack.quote_allocations.get().quantity, 100)

        next_card, _ = create_print_quote(
            tenant=tenant,
            quantity=1,
            price_book_version=price,
            idempotency_key="pack-101",
        )
        self.assertEqual(next_card.pack_quantity, 0)
        self.assertEqual(next_card.billable_quantity, 1)

    def test_accepted_quote_does_not_change_after_new_price_publication(self):
        tenant = create_tenant("frozen")
        create_subscription(tenant)
        version_one = create_price_version(code="frozen-prices", tiers=((1, None, "5.00"),))
        quote, _ = create_print_quote(
            tenant=tenant,
            quantity=10,
            price_book_version=version_one,
            idempotency_key="frozen-quote",
        )
        accept_quote(quote=quote)
        frozen_snapshot = quote.snapshot.copy()
        frozen_total = quote.total_amount

        create_price_version(
            code="frozen-prices",
            version=2,
            tiers=((1, None, "8.00"),),
        )
        quote.refresh_from_db()

        self.assertEqual(quote.price_book_version, version_one)
        self.assertEqual(quote.total_amount, frozen_total)
        self.assertEqual(quote.snapshot, frozen_snapshot)
        quote.total_amount = Decimal("1.00")
        with self.assertRaises(ValidationError):
            quote.save()


class ConcurrentUsageTests(TransactionTestCase):
    reset_sequences = True

    @skipUnlessDBFeature("has_select_for_update")
    def test_concurrent_retry_converges_on_one_usage_event(self):
        tenant = create_tenant("concurrent")
        create_subscription(tenant, issuance_limit=5)
        tenant_pk = tenant.pk

        def issue():
            close_old_connections()
            local_tenant = Tenant.objects.get(pk=tenant_pk)
            result = record_card_issuance(tenant=local_tenant, card_identity="same")
            close_old_connections()
            return result.event.pk

        with ThreadPoolExecutor(max_workers=2) as pool:
            event_ids = list(pool.map(lambda _: issue(), range(2)))

        self.assertEqual(len(set(event_ids)), 1)
        self.assertEqual(UsageEvent.objects.count(), 1)
