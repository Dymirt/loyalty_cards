"""Safely generate immutable physical-card artifacts through the shared service."""

import json

from django.core.management.base import BaseCommand, CommandError

from dotykacka.models import CardDesign, PhysicalCard, Tenant
from dotykacka.services.card_designs import generate_card_artifacts


class Command(BaseCommand):
    help = "Generate immutable tenant card artifacts; requires bounded selection."

    def add_arguments(self, parser):
        parser.add_argument("--tenant", required=True, help="Tenant slug.")
        parser.add_argument("--design-version", type=int)
        parser.add_argument("--card-code", action="append", dest="card_codes")
        parser.add_argument("--start", type=int)
        parser.add_argument("--end", type=int)
        parser.add_argument("--max-cards", type=int, default=100)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        try:
            tenant = Tenant.objects.get(slug=options["tenant"], is_active=True)
        except Tenant.DoesNotExist as exc:
            raise CommandError("Tenant does not exist.") from exc
        designs = CardDesign.objects.filter(tenant=tenant)
        if options["design_version"]:
            designs = designs.filter(version=options["design_version"])
        design = designs.first()
        if design is None:
            raise CommandError("Published tenant design does not exist.")

        cards = PhysicalCard.objects.filter(tenant=tenant).select_related("batch")
        card_codes = options.get("card_codes") or []
        start = options.get("start")
        end = options.get("end")
        if card_codes and (start is not None or end is not None):
            raise CommandError("Use card codes or a numeric range, not both.")
        if card_codes:
            cards = cards.filter(code__in=card_codes)
        elif start is not None and end is not None:
            if start < 1 or end < start:
                raise CommandError("Card range is invalid.")
            cards = cards.filter(number__gte=start, number__lte=end)
        else:
            raise CommandError("Provide --card-code or both --start and --end.")
        cards = list(cards.order_by("number"))
        if not cards:
            raise CommandError("No tenant cards matched the selection.")
        if options["max_cards"] < 1 or len(cards) > options["max_cards"]:
            raise CommandError("Selection exceeds --max-cards.")
        if card_codes and len(cards) != len(set(card_codes)):
            raise CommandError("One or more selected card codes do not belong to the tenant.")

        result = {
            "status": "planned" if options["dry_run"] else "generated",
            "tenant": tenant.slug,
            "design_version": design.version,
            "design_checksum": design.design_checksum,
            "card_count": len(cards),
            "cards": [card.code for card in cards],
            "artifacts": [],
        }
        if not options["dry_run"]:
            for card in cards:
                artifacts = generate_card_artifacts(design=design, physical_card=card)
                result["artifacts"].append(
                    {
                        "card": card.code,
                        "paths": [artifact.storage_path for artifact in artifacts],
                    }
                )
        self.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True))
