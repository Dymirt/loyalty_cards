"""Read-only Phase 3 tenant design and Wallet identity verification."""

import json

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db.models import F

from dotykacka.models import CardBatch, CardDesign, Tenant, TenantBrandRevision, WalletPass


class Command(BaseCommand):
    help = "Verify additive card-design and Wallet backfill aggregates without changes."

    def add_arguments(self, parser):
        parser.add_argument("--tenant", default=settings.LEGACY_DEFAULT_TENANT_SLUG)
        parser.add_argument("--expect-designs", type=int, default=1)
        parser.add_argument("--expect-brand-revisions", type=int, default=1)
        parser.add_argument("--expect-wallets", type=int, default=267)
        parser.add_argument("--expect-linked-batches", type=int, default=1)

    def handle(self, *args, **options):
        try:
            tenant = Tenant.objects.get(slug=options["tenant"])
        except Tenant.DoesNotExist as exc:
            raise CommandError("Tenant does not exist; no data was changed.") from exc
        result = {
            "status": "ok",
            "tenant": tenant.slug,
            "design_count": CardDesign.objects.filter(tenant=tenant).count(),
            "brand_revision_count": TenantBrandRevision.objects.filter(tenant=tenant).count(),
            "wallet_count": WalletPass.objects.filter(tenant=tenant).count(),
            "wallet_customer_mismatch_count": WalletPass.objects.filter(tenant=tenant).exclude(
                customer__tenant=tenant
            ).count(),
            "wallet_card_mismatch_count": WalletPass.objects.filter(
                tenant=tenant,
                physical_card__isnull=False,
            ).exclude(physical_card__tenant=tenant).count(),
            "wallet_missing_apple_serial_count": WalletPass.objects.filter(
                tenant=tenant,
                apple_serial__isnull=True,
            ).count(),
            "linked_batch_count": CardBatch.objects.filter(
                tenant=tenant,
                design__isnull=False,
            ).count(),
            "cross_tenant_design_batch_count": CardBatch.objects.filter(
                tenant=tenant,
                design__isnull=False,
            ).exclude(design__tenant=F("tenant")).count(),
        }
        expectations = {
            "design_count": options["expect_designs"],
            "brand_revision_count": options["expect_brand_revisions"],
            "wallet_count": options["expect_wallets"],
            "linked_batch_count": options["expect_linked_batches"],
            "wallet_customer_mismatch_count": 0,
            "wallet_card_mismatch_count": 0,
            "wallet_missing_apple_serial_count": 0,
            "cross_tenant_design_batch_count": 0,
        }
        mismatches = {
            key: {"expected": expected, "actual": result[key]}
            for key, expected in expectations.items()
            if result[key] != expected
        }
        if mismatches:
            result["status"] = "error"
            result["mismatches"] = mismatches
        self.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True))
        if mismatches:
            raise CommandError("Card-design backfill verification failed; no data was changed.")
