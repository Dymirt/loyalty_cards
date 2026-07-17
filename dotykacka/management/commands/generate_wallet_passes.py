"""Bounded tenant Wallet generation through the shared service layer."""

import json

from django.core.management.base import BaseCommand, CommandError

from dotykacka.models import Klient, Tenant
from dotykacka.services.wallets import (
    ensure_apple_wallet_pass,
    generate_google_wallet_for_klient,
)


class Command(BaseCommand):
    help = "Generate tenant Wallet artifacts; supports a read-only --dry-run."

    def add_arguments(self, parser):
        parser.add_argument("--tenant", required=True, help="Tenant slug.")
        parser.add_argument("--customer-code", action="append", dest="customer_codes")
        parser.add_argument("--start", type=int)
        parser.add_argument("--end", type=int)
        parser.add_argument("--wallet", choices=("apple", "google", "both"), default="both")
        parser.add_argument("--max-customers", type=int, default=100)
        parser.add_argument("--force-apple", action="store_true")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        try:
            tenant = Tenant.objects.get(slug=options["tenant"], is_active=True)
        except Tenant.DoesNotExist as exc:
            raise CommandError("Tenant does not exist.") from exc
        customers = Klient.objects.filter(tenant=tenant)
        customer_codes = options.get("customer_codes") or []
        start = options.get("start")
        end = options.get("end")
        if customer_codes and (start is not None or end is not None):
            raise CommandError("Use customer codes or a numeric range, not both.")
        if customer_codes:
            customers = customers.filter(klient_id__in=customer_codes)
        elif start is not None and end is not None:
            if start < 1 or end < start:
                raise CommandError("Customer range is invalid.")
            codes = [f"{tenant.card_prefix}-{number}" for number in range(start, end + 1)]
            customers = customers.filter(klient_id__in=codes)
        else:
            raise CommandError("Provide --customer-code or both --start and --end.")
        customers = list(customers.order_by("klient_id"))
        if not customers:
            raise CommandError("No tenant customers matched the selection.")
        if options["max_customers"] < 1 or len(customers) > options["max_customers"]:
            raise CommandError("Selection exceeds --max-customers.")
        if customer_codes and len(customers) != len(set(customer_codes)):
            raise CommandError("One or more customer codes do not belong to the tenant.")

        result = {
            "status": "planned" if options["dry_run"] else "generated",
            "tenant": tenant.slug,
            "wallet": options["wallet"],
            "customer_count": len(customers),
            "customers": [customer.klient_id for customer in customers],
        }
        if not options["dry_run"]:
            for customer in customers:
                if options["wallet"] in ("apple", "both"):
                    ensure_apple_wallet_pass(customer, force=options["force_apple"])
                if options["wallet"] in ("google", "both"):
                    generate_google_wallet_for_klient(customer)
        self.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True))
