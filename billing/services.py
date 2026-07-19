"""Transactional subscription, entitlement, usage, and quote services."""

import calendar
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q, Sum
from django.utils import timezone
from django.utils.translation import gettext as _

from tenants.models import TenantMembership

from .models import (
    BillingPeriod,
    CardPack,
    CardPackAllocation,
    CardPriceTier,
    EntitlementPolicy,
    PlanVersion,
    PriceBookVersion,
    PrintQuoteConsumption,
    Quote,
    QuoteLine,
    TenantSubscription,
    UsageEvent,
)


CENT = Decimal("0.01")


class CommercialConfigurationError(ValidationError):
    pass


class EntitlementLimitError(ValidationError):
    pass


@dataclass(frozen=True)
class UsageResult:
    managed: bool
    event: UsageEvent | None = None
    created: bool = False


def _money(value):
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def active_subscription_for_tenant(*, tenant, at=None, for_update=False):
    at = at or timezone.now()
    queryset = TenantSubscription.objects.select_related(
        "plan_version",
        "plan_version__plan",
        "plan_version__entitlement_policy",
    ).filter(
        tenant=tenant,
        status=TenantSubscription.Status.ACTIVE,
        starts_at__lte=at,
    ).filter(Q(ends_at__isnull=True) | Q(ends_at__gt=at))
    if for_update:
        queryset = queryset.select_for_update()
    subscriptions = list(queryset.order_by("-starts_at", "-pk")[:2])
    if len(subscriptions) > 1:
        raise CommercialConfigurationError(
            _("Firma ma nakładające się aktywne subskrypcje; operator platformy musi je uporządkować.")
        )
    return subscriptions[0] if subscriptions else None


def _add_interval(value: datetime, interval: str):
    if interval == PlanVersion.BillingInterval.YEARLY:
        year, month = value.year + 1, value.month
    else:
        month_index = value.year * 12 + value.month
        year, month_zero = divmod(month_index, 12)
        month = month_zero + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def period_bounds(*, subscription, at=None):
    at = at or timezone.now()
    if at < subscription.starts_at:
        raise CommercialConfigurationError(_("Subskrypcja jeszcze się nie rozpoczęła."))
    start = subscription.starts_at
    end = _add_interval(start, subscription.plan_version.billing_interval)
    while end <= at:
        start = end
        end = _add_interval(start, subscription.plan_version.billing_interval)
    if subscription.ends_at and end > subscription.ends_at:
        end = subscription.ends_at
    return start, end


def current_billing_period(*, subscription, at=None, for_update=False):
    start, end = period_bounds(subscription=subscription, at=at)
    period, _ = BillingPeriod.objects.get_or_create(
        subscription=subscription,
        starts_at=start,
        ends_at=end,
    )
    if for_update:
        period = BillingPeriod.objects.select_for_update().get(pk=period.pk)
    return period


@transaction.atomic
def ensure_active_seat_available(*, tenant, membership=None, at=None):
    """Validate one invite/reactivation without changing any existing membership."""

    subscription = active_subscription_for_tenant(
        tenant=tenant,
        at=at,
        for_update=True,
    )
    if subscription is None:
        return None
    policy = subscription.plan_version.entitlement_policy
    if policy.active_seat_limit is None:
        return subscription
    memberships = TenantMembership.objects.filter(tenant=tenant, is_active=True)
    if membership is not None and membership.pk and membership.is_active:
        memberships = memberships.exclude(pk=membership.pk)
    if memberships.count() + 1 > policy.active_seat_limit:
        raise EntitlementLimitError(
            _("Osiągnięto limit aktywnych użytkowników (%(limit)s).")
            % {"limit": policy.active_seat_limit}
        )
    return subscription


@transaction.atomic
def record_card_issuance(
    *,
    tenant,
    card_identity,
    physical=True,
    occurred_at=None,
    metadata=None,
):
    """Record the first successful identity assignment exactly once.

    A tenant without an active subscription remains in the explicit legacy
    unmanaged state. That preserves existing operation without inventing or
    back-billing historical usage.
    """

    occurred_at = occurred_at or timezone.now()
    identity = str(card_identity)
    kind = (
        UsageEvent.Kind.PHYSICAL_CARD_ISSUED
        if physical
        else UsageEvent.Kind.VIRTUAL_CARD_ISSUED
    )
    key = f"card-issued:{'physical' if physical else 'virtual'}:{identity}"
    existing = UsageEvent.objects.filter(tenant=tenant, idempotency_key=key).first()
    if existing:
        return UsageResult(managed=True, event=existing, created=False)

    subscription = active_subscription_for_tenant(
        tenant=tenant,
        at=occurred_at,
        for_update=True,
    )
    if subscription is None:
        return UsageResult(managed=False)
    period = current_billing_period(
        subscription=subscription,
        at=occurred_at,
        for_update=True,
    )
    policy = subscription.plan_version.entitlement_policy
    if policy.card_issuance_limit is not None:
        used = UsageEvent.objects.filter(
            billing_period=period,
            kind__in=(
                UsageEvent.Kind.PHYSICAL_CARD_ISSUED,
                UsageEvent.Kind.VIRTUAL_CARD_ISSUED,
            ),
        ).aggregate(total=Sum("quantity"))["total"] or 0
        if used + 1 > policy.card_issuance_limit:
            raise EntitlementLimitError(
                _("Osiągnięto limit wydanych kart (%(limit)s).")
                % {"limit": policy.card_issuance_limit}
            )
    try:
        with transaction.atomic():
            event = UsageEvent.objects.create(
                tenant=tenant,
                subscription=subscription,
                billing_period=period,
                kind=kind,
                quantity=1,
                idempotency_key=key,
                reference_type="PhysicalCard" if physical else "VirtualCard",
                reference_id=identity,
                metadata=metadata or {},
                occurred_at=occurred_at,
            )
    except IntegrityError:
        event = UsageEvent.objects.get(tenant=tenant, idempotency_key=key)
        return UsageResult(managed=True, event=event, created=False)
    return UsageResult(managed=True, event=event, created=True)


@transaction.atomic
def publish_plan_version(*, plan_version, actor=None):
    plan_version = PlanVersion.objects.select_for_update().get(pk=plan_version.pk)
    if plan_version.published_at:
        return plan_version
    try:
        plan_version.entitlement_policy
    except EntitlementPolicy.DoesNotExist as exc:
        raise CommercialConfigurationError(
            _("Dodaj zasady limitów przed opublikowaniem wersji planu.")
        ) from exc
    plan_version.full_clean()
    plan_version.created_by = plan_version.created_by or actor
    plan_version.published_at = timezone.now()
    plan_version.save(update_fields=("created_by", "published_at"))
    return plan_version


def _validated_tiers(price_book_version):
    tiers = list(price_book_version.card_price_tiers.order_by("minimum_quantity"))
    if not tiers or tiers[0].minimum_quantity != 1:
        raise CommercialConfigurationError(_("Progi cenowe muszą zaczynać się od liczby 1."))
    expected = 1
    for position, tier in enumerate(tiers):
        if tier.minimum_quantity != expected:
            raise CommercialConfigurationError(_("Progi cenowe nie mogą się nakładać ani mieć przerw."))
        if tier.maximum_quantity is None:
            if position != len(tiers) - 1:
                raise CommercialConfigurationError(_("Tylko ostatni próg może nie mieć górnej granicy."))
            expected = None
        else:
            expected = tier.maximum_quantity + 1
    if expected is not None:
        raise CommercialConfigurationError(_("Ostatni próg cenowy nie może mieć górnej granicy."))
    return tiers


@transaction.atomic
def publish_price_book_version(*, price_book_version, actor=None):
    price_book_version = PriceBookVersion.objects.select_for_update().get(
        pk=price_book_version.pk
    )
    if price_book_version.published_at:
        return price_book_version
    _validated_tiers(price_book_version)
    price_book_version.full_clean()
    price_book_version.created_by = price_book_version.created_by or actor
    price_book_version.published_at = timezone.now()
    price_book_version.save(update_fields=("created_by", "published_at"))
    return price_book_version


def _tier_for_quantity(price_book_version, quantity):
    if quantity <= 0:
        return None
    for tier in _validated_tiers(price_book_version):
        if tier.minimum_quantity <= quantity and (
            tier.maximum_quantity is None or quantity <= tier.maximum_quantity
        ):
            return tier
    raise CommercialConfigurationError(_("Żaden opublikowany próg cenowy nie obejmuje tej liczby kart."))


def _available_pack_rows(*, tenant, currency, at, for_update=False):
    packs = CardPack.objects.filter(
        tenant=tenant,
        currency=currency,
        is_active=True,
    ).filter(Q(expires_at__isnull=True) | Q(expires_at__gt=at))
    if for_update:
        packs = packs.select_for_update()
    rows = []
    for pack in packs.order_by("expires_at", "created_at", "pk"):
        reserved = pack.quote_allocations.filter(
            quote__print_consumption__isnull=True,
        ).aggregate(total=Sum("quantity"))["total"] or 0
        available = pack.purchased_quantity - pack.consumed_quantity - reserved
        if available > 0:
            rows.append((pack, available))
    return rows


def _quote_snapshot(*, subscription, period, price_book_version, policy, allocations, tier):
    return {
        "plan": {
            "code": subscription.plan_version.plan.code,
            "name": subscription.plan_version.plan.name,
            "version": subscription.plan_version.version,
            "billing_interval": subscription.plan_version.billing_interval,
            "recurring_amount": str(subscription.plan_version.recurring_amount),
            "currency": subscription.plan_version.currency,
        },
        "entitlements": {
            "active_seat_limit": policy.active_seat_limit,
            "card_issuance_limit": policy.card_issuance_limit,
            "included_print_quantity": policy.included_print_quantity,
            "unused_allowance_rolls_over": policy.unused_allowance_rolls_over,
            "print_overage_allowed": policy.print_overage_allowed,
        },
        "billing_period": {
            "id": period.pk,
            "starts_at": period.starts_at.isoformat(),
            "ends_at": period.ends_at.isoformat(),
        },
        "price_book": {
            "code": price_book_version.price_book.code,
            "name": price_book_version.price_book.name,
            "version": price_book_version.version,
            "currency": price_book_version.currency,
            "tax_display": price_book_version.tax_display,
            "tax_rate": str(price_book_version.tax_rate),
            "shipping_amount": str(price_book_version.shipping_amount),
        },
        "tier": (
            {
                "minimum_quantity": tier.minimum_quantity,
                "maximum_quantity": tier.maximum_quantity,
                "unit_amount": str(tier.unit_amount),
            }
            if tier
            else None
        ),
        "proposed_pack_allocations": [
            {"card_pack_id": pack.pk, "name": pack.name, "quantity": quantity}
            for pack, quantity in allocations
        ],
    }


def _periods_elapsed(*, subscription, current_period):
    count = 1
    end = _add_interval(
        subscription.starts_at,
        subscription.plan_version.billing_interval,
    )
    while end <= current_period.starts_at:
        count += 1
        end = _add_interval(end, subscription.plan_version.billing_interval)
    return count


def _available_print_allowance(*, subscription, period, policy):
    if policy.unused_allowance_rolls_over:
        allowance_total = policy.included_print_quantity * _periods_elapsed(
            subscription=subscription,
            current_period=period,
        )
        quote_scope = Quote.objects.filter(subscription=subscription)
        consumption_scope = PrintQuoteConsumption.objects.filter(
            quote__subscription=subscription,
        )
    else:
        allowance_total = policy.included_print_quantity
        quote_scope = Quote.objects.filter(billing_period=period)
        consumption_scope = PrintQuoteConsumption.objects.filter(
            quote__billing_period=period,
        )
    produced_included = consumption_scope.aggregate(
        total=Sum("included_quantity")
    )["total"] or 0
    reserved_allowance = quote_scope.filter(
        status=Quote.Status.ACCEPTED,
        print_consumption__isnull=True,
    ).aggregate(total=Sum("included_quantity"))["total"] or 0
    return max(0, allowance_total - produced_included - reserved_allowance)


@transaction.atomic
def create_print_quote(
    *,
    tenant,
    quantity,
    price_book_version,
    idempotency_key,
    actor=None,
    at=None,
):
    """Freeze allowance → pack → tier → shipping/tax calculation in a quote."""

    at = at or timezone.now()
    if quantity <= 0:
        raise ValidationError({"quantity": _("Liczba kart musi być większa od zera.")})
    existing = Quote.objects.filter(tenant=tenant, idempotency_key=idempotency_key).first()
    if existing:
        if existing.quantity != quantity:
            raise ValidationError(_("Ten klucz idempotencji został już użyty dla innej liczby kart."))
        return existing, False
    subscription = active_subscription_for_tenant(tenant=tenant, at=at, for_update=True)
    if subscription is None:
        raise CommercialConfigurationError(
            _("Przed utworzeniem kalkulacji druku wymagana jest aktywna, opublikowana subskrypcja.")
        )
    price_book_version = PriceBookVersion.objects.select_related("price_book").get(
        pk=price_book_version.pk,
        published_at__isnull=False,
        price_book__is_active=True,
    )
    if subscription.plan_version.currency != price_book_version.currency:
        raise CommercialConfigurationError(
            _("Waluty subskrypcji i cennika muszą być zgodne.")
        )
    period = current_billing_period(subscription=subscription, at=at, for_update=True)
    policy = subscription.plan_version.entitlement_policy

    allowance = _available_print_allowance(
        subscription=subscription,
        period=period,
        policy=policy,
    )
    included_quantity = min(quantity, allowance)
    remainder = quantity - included_quantity

    allocations = []
    for pack, available in _available_pack_rows(
        tenant=tenant,
        currency=price_book_version.currency,
        at=at,
        for_update=True,
    ):
        allocated = min(remainder, available)
        if allocated:
            allocations.append((pack, allocated))
            remainder -= allocated
        if remainder == 0:
            break
    pack_quantity = sum(value for _, value in allocations)
    billable_quantity = remainder
    if billable_quantity and not policy.print_overage_allowed:
        raise EntitlementLimitError(
            _("Limit w abonamencie i pakiety kart nie pokrywają tego zamówienia.")
        )

    tier = _tier_for_quantity(price_book_version, billable_quantity)
    unit_amount = tier.unit_amount if tier else Decimal("0.00")
    subtotal = _money(unit_amount * billable_quantity)
    shipping = _money(price_book_version.shipping_amount)
    taxable_base = subtotal + shipping
    if price_book_version.tax_display == PlanVersion.TaxDisplay.EXCLUSIVE:
        tax = _money(taxable_base * price_book_version.tax_rate)
        total = taxable_base + tax
    elif price_book_version.tax_display == PlanVersion.TaxDisplay.INCLUSIVE:
        divisor = Decimal("1.0000") + price_book_version.tax_rate
        tax = _money(taxable_base - (taxable_base / divisor)) if divisor else Decimal("0.00")
        total = taxable_base
    else:
        tax = Decimal("0.00")
        total = taxable_base
    total = _money(total)
    snapshot = _quote_snapshot(
        subscription=subscription,
        period=period,
        price_book_version=price_book_version,
        policy=policy,
        allocations=allocations,
        tier=tier,
    )
    try:
        with transaction.atomic():
            quote = Quote.objects.create(
                tenant=tenant,
                subscription=subscription,
                billing_period=period,
                price_book_version=price_book_version,
                status=Quote.Status.DRAFT,
                idempotency_key=idempotency_key,
                quantity=quantity,
                included_quantity=included_quantity,
                pack_quantity=pack_quantity,
                billable_quantity=billable_quantity,
                currency=price_book_version.currency,
                subtotal_amount=subtotal,
                shipping_amount=shipping,
                tax_amount=tax,
                total_amount=total,
                snapshot=snapshot,
                created_by=actor,
            )
            position = 1
            line_specs = []
            if included_quantity:
                line_specs.append(
                    (QuoteLine.Kind.INCLUDED, "Included print allowance", included_quantity, Decimal("0.00"), Decimal("0.00"), {})
                )
            if pack_quantity:
                line_specs.append(
                    (QuoteLine.Kind.PACK, "Eligible prepaid card packs", pack_quantity, Decimal("0.00"), Decimal("0.00"), {"allocations": snapshot["proposed_pack_allocations"]})
                )
            if billable_quantity:
                line_specs.append(
                    (QuoteLine.Kind.PRODUCTION, "Physical card production", billable_quantity, unit_amount, subtotal, snapshot["tier"] or {})
                )
            line_specs.append(
                (QuoteLine.Kind.SHIPPING, "Shipping", 1, shipping, shipping, {})
            )
            line_specs.append(
                (QuoteLine.Kind.TAX, "Tax shown", 1, tax, tax, {"display": price_book_version.tax_display, "rate": str(price_book_version.tax_rate)})
            )
            for kind, description, line_quantity, line_unit, line_total, metadata in line_specs:
                QuoteLine.objects.create(
                    quote=quote,
                    position=position,
                    kind=kind,
                    description=description,
                    quantity=line_quantity,
                    unit_amount=_money(line_unit),
                    total_amount=_money(line_total),
                    metadata=metadata,
                )
                position += 1
    except IntegrityError:
        quote = Quote.objects.get(tenant=tenant, idempotency_key=idempotency_key)
        if quote.quantity != quantity:
            raise ValidationError(_("Ten klucz idempotencji został już użyty dla innej liczby kart."))
        return quote, False
    return quote, True


@transaction.atomic
def accept_quote(*, quote, at=None):
    at = at or timezone.now()
    quote = Quote.objects.select_for_update().get(pk=quote.pk)
    if quote.status == Quote.Status.ACCEPTED:
        return quote, False
    if quote.status != Quote.Status.DRAFT:
        raise ValidationError(_("Można zaakceptować tylko wersję roboczą kalkulacji."))
    if quote.expires_at and quote.expires_at <= at:
        raise ValidationError(_("Ta kalkulacja wygasła."))
    if at < quote.billing_period.starts_at or at >= quote.billing_period.ends_at:
        raise ValidationError(_("Okres rozliczeniowy tej kalkulacji zakończył się; utwórz nową kalkulację."))

    subscription = TenantSubscription.objects.select_for_update().select_related(
        "plan_version__entitlement_policy"
    ).get(pk=quote.subscription_id)
    period = BillingPeriod.objects.select_for_update().get(pk=quote.billing_period_id)
    allowance = _available_print_allowance(
        subscription=subscription,
        period=period,
        policy=subscription.plan_version.entitlement_policy,
    )
    if quote.included_quantity > allowance:
        raise EntitlementLimitError(
            _("Limit w abonamencie zarezerwowała inna zaakceptowana kalkulacja; utwórz nową kalkulację.")
        )

    proposed = quote.snapshot.get("proposed_pack_allocations", [])
    for allocation in proposed:
        pack = CardPack.objects.select_for_update().get(
            pk=allocation["card_pack_id"],
            tenant=quote.tenant,
            is_active=True,
        )
        if pack.currency != quote.currency or (pack.expires_at and pack.expires_at <= at):
            raise EntitlementLimitError(_("Proponowany pakiet kart nie może już zostać użyty."))
        reserved = pack.quote_allocations.filter(
            quote__print_consumption__isnull=True,
        ).aggregate(total=Sum("quantity"))["total"] or 0
        available = pack.purchased_quantity - pack.consumed_quantity - reserved
        quantity = int(allocation["quantity"])
        if quantity > available:
            raise EntitlementLimitError(_("Proponowany pakiet kart nie ma już wystarczającego salda."))
        CardPackAllocation.objects.create(
            quote=quote,
            card_pack=pack,
            quantity=quantity,
        )
    quote.status = Quote.Status.ACCEPTED
    quote.accepted_at = at
    quote.save(update_fields=("status", "accepted_at"))
    return quote, True


@transaction.atomic
def consume_print_quote(*, quote, reference_type, reference_id, at=None):
    """Consume one accepted quote exactly once at production allocation."""

    at = at or timezone.now()
    quote = (
        Quote.objects.select_for_update()
        .select_related("subscription", "billing_period")
        .get(pk=quote.pk)
    )
    try:
        return quote.print_consumption, False
    except PrintQuoteConsumption.DoesNotExist:
        pass
    if quote.status != Quote.Status.ACCEPTED:
        raise ValidationError(_("Do produkcji można rozliczyć tylko zaakceptowaną kalkulację."))

    allocations = list(
        CardPackAllocation.objects.filter(quote=quote).select_related("card_pack")
    )
    if sum(item.quantity for item in allocations) != quote.pack_quantity:
        raise CommercialConfigurationError(
            _("Rezerwacja pakietów kart dla zaakceptowanej kalkulacji jest niepełna.")
        )
    for allocation in allocations:
        pack = CardPack.objects.select_for_update().get(pk=allocation.card_pack_id)
        if pack.consumed_quantity + allocation.quantity > pack.purchased_quantity:
            raise EntitlementLimitError(_("Zarezerwowanego pakietu kart nie można bezpiecznie rozliczyć."))
        pack.consumed_quantity += allocation.quantity
        pack.save(update_fields=("consumed_quantity",))

    usage_event, _ = UsageEvent.objects.get_or_create(
        tenant=quote.tenant,
        idempotency_key=f"physical-card-produced:quote:{quote.pk}",
        defaults={
            "subscription": quote.subscription,
            "billing_period": quote.billing_period,
            "kind": UsageEvent.Kind.PHYSICAL_CARD_PRODUCED,
            "quantity": quote.quantity,
            "reference_type": reference_type,
            "reference_id": str(reference_id),
            "metadata": {
                "quote_id": quote.pk,
                "included_quantity": quote.included_quantity,
                "pack_quantity": quote.pack_quantity,
                "billable_quantity": quote.billable_quantity,
            },
            "occurred_at": at,
        },
    )
    consumption = PrintQuoteConsumption(
        quote=quote,
        usage_event=usage_event,
        included_quantity=quote.included_quantity,
        pack_quantity=quote.pack_quantity,
        billable_quantity=quote.billable_quantity,
        reference_type=reference_type,
        reference_id=str(reference_id),
        consumed_at=at,
    )
    consumption.full_clean()
    consumption.save()
    return consumption, True


def tenant_billing_summary(*, tenant, at=None):
    at = at or timezone.now()
    subscription = active_subscription_for_tenant(tenant=tenant, at=at)
    if subscription is None:
        return {
            "subscription": None,
            "period": None,
            "policy": None,
            "active_seats": TenantMembership.objects.filter(
                tenant=tenant, is_active=True
            ).count(),
            "usage": {},
        }
    period = current_billing_period(subscription=subscription, at=at)
    usage = {
        row["kind"]: row["total"]
        for row in UsageEvent.objects.filter(billing_period=period)
        .values("kind")
        .annotate(total=Sum("quantity"))
    }
    return {
        "subscription": subscription,
        "period": period,
        "policy": subscription.plan_version.entitlement_policy,
        "active_seats": TenantMembership.objects.filter(
            tenant=tenant, is_active=True
        ).count(),
        "usage": usage,
    }
