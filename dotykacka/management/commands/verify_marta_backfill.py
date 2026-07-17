"""Read-only aggregate verification for the Phase 1 Marta backfill."""

import json

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from dotykacka.models import (
    AccessToken,
    IntegrationConnection,
    Klient,
    PhysicalCard,
    Tenant,
)


class Command(BaseCommand):
    help = "Verify Marta tenant ownership and inventory aggregates without changing data."

    def add_arguments(self, parser):
        parser.add_argument(
            "--tenant-slug",
            default=settings.LEGACY_DEFAULT_TENANT_SLUG,
        )
        parser.add_argument("--expect-memberships", type=int, default=1)
        parser.add_argument("--expect-customers", type=int, default=267)
        parser.add_argument("--expect-tokens", type=int, default=261)
        parser.add_argument("--expect-cards", type=int, default=600)
        parser.add_argument("--expect-assigned", type=int, default=267)
        parser.add_argument("--expect-available", type=int, default=333)

    def handle(self, *args, **options):
        try:
            tenant = Tenant.objects.get(slug=options["tenant_slug"])
        except Tenant.DoesNotExist as exc:
            raise CommandError("Marta tenant does not exist; no data was changed.") from exc

        connections = {
            connection.provider: connection
            for connection in IntegrationConnection.objects.filter(tenant=tenant)
        }
        result = {
            "status": "ok",
            "tenant_count": Tenant.objects.filter(pk=tenant.pk).count(),
            "membership_count": tenant.memberships.count(),
            "customer_count": Klient.objects.filter(tenant=tenant).count(),
            "token_count": AccessToken.objects.filter(connection__tenant=tenant).count(),
            "physical_card_count": PhysicalCard.objects.filter(tenant=tenant).count(),
            "assigned_card_count": PhysicalCard.objects.filter(
                tenant=tenant,
                status=PhysicalCard.Status.ASSIGNED,
                customer__isnull=False,
            ).count(),
            "available_card_count": PhysicalCard.objects.filter(
                tenant=tenant,
                status=PhysicalCard.Status.AVAILABLE,
                customer__isnull=True,
            ).count(),
            "integration_providers": sorted(connections),
            "dotykacka_secret_configured": bool(
                connections.get(IntegrationConnection.Provider.DOTYKACKA)
                and connections[IntegrationConnection.Provider.DOTYKACKA].has_secret(
                    "authorization_token"
                )
            ),
            "brevo_secret_configured": bool(
                connections.get(IntegrationConnection.Provider.BREVO)
                and connections[IntegrationConnection.Provider.BREVO].has_secret("api_key")
            ),
        }
        expectations = {
            "membership_count": options["expect_memberships"],
            "customer_count": options["expect_customers"],
            "token_count": options["expect_tokens"],
            "physical_card_count": options["expect_cards"],
            "assigned_card_count": options["expect_assigned"],
            "available_card_count": options["expect_available"],
        }
        mismatches = {
            key: {"expected": expected, "actual": result[key]}
            for key, expected in expectations.items()
            if result[key] != expected
        }
        required_providers = {provider for provider, _ in IntegrationConnection.Provider.choices}
        if set(result["integration_providers"]) != required_providers:
            mismatches["integration_providers"] = {
                "expected": sorted(required_providers),
                "actual": result["integration_providers"],
            }
        if mismatches:
            result["status"] = "error"
            result["mismatches"] = mismatches

        self.stdout.write(json.dumps(result, sort_keys=True))
        if mismatches:
            raise CommandError("Marta backfill verification failed; no data was changed.")
