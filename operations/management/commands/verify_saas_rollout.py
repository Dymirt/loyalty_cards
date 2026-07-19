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


class Command(BaseCommand):
    help = "Run a read-only staged SaaS rollout check; optionally enforce Marta invariants."

    def add_arguments(self, parser):
        parser.add_argument("--expect-marta", action="store_true")

    def handle(self, *args, **options):
        tenant = get_default_tenant()
        counts = {
            "tenant": tenant.slug,
            "customers": Klient.objects.filter(tenant=tenant).count(),
            "cards": PhysicalCard.objects.filter(tenant=tenant).count(),
            "assigned_cards": PhysicalCard.objects.filter(
                tenant=tenant, status=PhysicalCard.Status.ASSIGNED
            ).count(),
            "available_cards": PhysicalCard.objects.filter(
                tenant=tenant, status=PhysicalCard.Status.AVAILABLE
            ).count(),
            "access_tokens": AccessToken.objects.filter(
                connection__tenant=tenant
            ).count(),
            "memberships": TenantMembership.objects.filter(tenant=tenant).count(),
            "integrations": IntegrationConnection.objects.filter(tenant=tenant).count(),
            "wallet_identities": WalletPass.objects.filter(tenant=tenant).count(),
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
            expected = {
                "customers": 267,
                "cards": 600,
                "assigned_cards": 267,
                "available_cards": 333,
                "access_tokens": 263,
                "memberships": 1,
                "integrations": 3,
                "wallet_identities": 267,
                "enrollments": 0,
                "print_requests": 0,
                "marketing_leads": 0,
            }
            mismatches = {
                key: {"expected": value, "actual": counts[key]}
                for key, value in expected.items()
                if counts[key] != value
            }
            if mismatches:
                raise CommandError(
                    "Marta rollout invariants differ: " + json.dumps(mismatches, sort_keys=True)
                )
        self.stdout.write(
            json.dumps({"counts": counts, "routes": routes, "mutation": "none"}, sort_keys=True)
        )
