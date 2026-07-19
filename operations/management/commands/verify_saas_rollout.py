import json

from django.core.management.base import BaseCommand, CommandError
from django.urls import reverse

from billing.models import Plan, PlanVersion, PriceBook, PriceBookVersion
from dotykacka.models import (
    AccessToken,
    IntegrationConnection,
    Klient,
    PhysicalCard,
    TenantMembership,
    WalletPass,
)
from enrollment.models import Enrollment
from marketing.models import MarketingLead
from printing.models import PrintRequest
from tenants.authorization import get_default_tenant


MARTA_BASELINE_MINIMUMS = {
    "customers": 267,
    "cards": 600,
    "cards_with_customer": 267,
    "access_tokens": 261,
    "memberships": 1,
    "wallet_identities": 267,
}


def _marta_invariant_mismatches(counts):
    """Protect Marta's historical baseline while allowing normal SaaS growth."""

    mismatches = {}
    for key, expected_minimum in MARTA_BASELINE_MINIMUMS.items():
        if counts[key] < expected_minimum:
            mismatches[key] = {
                "expected_minimum": expected_minimum,
                "actual": counts[key],
            }

    exact_relations = {
        "customer_card_ownership": (
            counts["cards_with_customer"],
            counts["customers"],
        ),
        "customer_wallet_identity": (
            counts["wallet_identities"],
            counts["customers"],
        ),
        "cross_tenant_card_customers": (
            counts["cross_tenant_card_customers"],
            0,
        ),
        "cross_tenant_card_batches": (
            counts["cross_tenant_card_batches"],
            0,
        ),
        "cross_tenant_wallet_customers": (
            counts["cross_tenant_wallet_customers"],
            0,
        ),
        "cross_tenant_wallet_cards": (
            counts["cross_tenant_wallet_cards"],
            0,
        ),
    }
    for key, (actual, expected) in exact_relations.items():
        if actual != expected:
            mismatches[key] = {"expected": expected, "actual": actual}

    required_providers = {
        value for value, _label in IntegrationConnection.Provider.choices
    }
    missing_providers = sorted(
        required_providers - set(counts["integration_providers"])
    )
    if missing_providers:
        mismatches["integration_providers"] = {
            "missing": missing_providers,
            "actual": counts["integration_providers"],
        }
    for key in ("dotykacka_refresh_token_configured", "brevo_api_key_configured"):
        if not counts[key]:
            mismatches[key] = {"expected": True, "actual": False}
    return mismatches


class Command(BaseCommand):
    help = "Run a read-only staged SaaS rollout check; optionally enforce Marta invariants."

    def add_arguments(self, parser):
        parser.add_argument("--expect-marta", action="store_true")

    def handle(self, *args, **options):
        tenant = get_default_tenant()
        physical_cards = PhysicalCard.objects.filter(tenant=tenant)
        wallets = WalletPass.objects.filter(tenant=tenant)
        connections = list(
            IntegrationConnection.objects.filter(tenant=tenant).order_by(
                "provider", "pk"
            )
        )
        connection_by_provider = {
            connection.provider: connection for connection in connections
        }
        counts = {
            "tenant": tenant.slug,
            "customers": Klient.objects.filter(tenant=tenant).count(),
            "cards": physical_cards.count(),
            "assigned_cards": physical_cards.filter(
                status=PhysicalCard.Status.ASSIGNED
            ).count(),
            "available_cards": physical_cards.filter(
                status=PhysicalCard.Status.AVAILABLE
            ).count(),
            "printed_cards": physical_cards.filter(
                status=PhysicalCard.Status.PRINTED
            ).count(),
            "void_cards": physical_cards.filter(
                status=PhysicalCard.Status.VOID
            ).count(),
            "cards_with_customer": physical_cards.filter(
                customer__isnull=False
            ).count(),
            "cross_tenant_card_customers": physical_cards.filter(
                customer__isnull=False
            ).exclude(customer__tenant=tenant).count(),
            "cross_tenant_card_batches": physical_cards.exclude(
                batch__tenant=tenant
            ).count(),
            "access_tokens": AccessToken.objects.filter(
                connection__tenant=tenant
            ).count(),
            "memberships": TenantMembership.objects.filter(tenant=tenant).count(),
            "integrations": len(connections),
            "integration_providers": [
                connection.provider for connection in connections
            ],
            "dotykacka_refresh_token_configured": bool(
                connection_by_provider.get(IntegrationConnection.Provider.DOTYKACKA)
                and connection_by_provider[
                    IntegrationConnection.Provider.DOTYKACKA
                ].has_secret("refresh_token")
            ),
            "brevo_api_key_configured": bool(
                connection_by_provider.get(IntegrationConnection.Provider.BREVO)
                and connection_by_provider[
                    IntegrationConnection.Provider.BREVO
                ].has_secret("api_key")
            ),
            "wallet_identities": wallets.count(),
            "cross_tenant_wallet_customers": wallets.exclude(
                customer__tenant=tenant
            ).count(),
            "cross_tenant_wallet_cards": wallets.filter(
                physical_card__isnull=False
            ).exclude(physical_card__tenant=tenant).count(),
            "enrollments": Enrollment.objects.filter(tenant=tenant).count(),
            "print_requests": PrintRequest.objects.filter(tenant=tenant).count(),
            "marketing_leads": MarketingLead.objects.count(),
            "plans": Plan.objects.count(),
            "plan_versions": PlanVersion.objects.count(),
            "price_books": PriceBook.objects.count(),
            "price_book_versions": PriceBookVersion.objects.count(),
        }
        routes = {
            "marketing": reverse("marketing:home"),
            "registration": reverse("enrollment:tenant_register", args=[tenant.slug]),
            "portal": reverse("tenants:portal", args=[tenant.slug]),
            "operations": reverse("operations:dashboard"),
        }
        if options["expect_marta"]:
            mismatches = _marta_invariant_mismatches(counts)
            if mismatches:
                raise CommandError(
                    "Marta rollout invariants differ: " + json.dumps(mismatches, sort_keys=True)
                )
        self.stdout.write(
            json.dumps({"counts": counts, "routes": routes, "mutation": "none"}, sort_keys=True)
        )
