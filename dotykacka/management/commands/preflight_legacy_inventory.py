"""Read-only validation of the Marta legacy database and card inventory."""

import json
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Count

from dotykacka.card_codes import CardCodeError, parse_card_code
from dotykacka.models import AccessToken, Klient


def expected_asset_paths(media_root: Path, prefix: str, number: int) -> tuple[Path, ...]:
    card_code = f"{prefix}-{number}"
    card_dir = media_root / "cards" / f"card-{number}"
    return (
        card_dir / f"{card_code}_front.jpg",
        card_dir / f"{card_code}_back.jpg",
        card_dir / "barcode.png",
        media_root / "cropped_images" / f"cropped_image_{number}.jpg",
        media_root / "output_passes" / f"pass_{number}.pkpass",
    )


class Command(BaseCommand):
    help = "Validate legacy card/customer aggregates and assets without changing data."

    def add_arguments(self, parser):
        parser.add_argument("--media-root", default=str(settings.MEDIA_ROOT))
        parser.add_argument("--prefix", default="MB")
        parser.add_argument("--start", type=int, default=1)
        parser.add_argument("--end", type=int, default=600)
        parser.add_argument("--expect-customers", type=int)
        parser.add_argument("--expect-tokens", type=int)
        parser.add_argument("--expect-users", type=int)
        parser.add_argument("--skip-assets", action="store_true")
        parser.add_argument("--json", action="store_true", dest="as_json")

    def handle(self, *args, **options):
        start = options["start"]
        end = options["end"]
        prefix = options["prefix"].strip().upper()
        if start < 1 or end < start:
            raise CommandError("The inventory range must satisfy 1 <= start <= end.")

        card_codes = list(Klient.objects.values_list("klient_id", flat=True))
        duplicate_groups = Klient.objects.values("klient_id").annotate(
            total=Count("id")
        ).filter(total__gt=1)
        duplicate_count = duplicate_groups.count()

        invalid_code_count = 0
        out_of_range_count = 0
        assigned_numbers = set()
        for raw_code in card_codes:
            try:
                parsed = parse_card_code(raw_code, expected_prefix=prefix)
            except CardCodeError:
                invalid_code_count += 1
                continue
            if not start <= parsed.number <= end:
                out_of_range_count += 1
                continue
            assigned_numbers.add(parsed.number)

        missing_assets = []
        if not options["skip_assets"]:
            media_root = Path(options["media_root"])
            for number in range(start, end + 1):
                for asset_path in expected_asset_paths(media_root, prefix, number):
                    if not asset_path.is_file():
                        missing_assets.append(str(asset_path))

        customer_count = len(card_codes)
        token_count = AccessToken.objects.count()
        user_count = get_user_model().objects.count()
        expected_card_count = end - start + 1
        result = {
            "status": "ok",
            "customer_count": customer_count,
            "user_count": user_count,
            "token_count": token_count,
            "duplicate_code_groups": duplicate_count,
            "invalid_code_count": invalid_code_count,
            "out_of_range_code_count": out_of_range_count,
            "expected_card_count": expected_card_count,
            "assigned_card_count": len(assigned_numbers),
            "available_card_count": expected_card_count - len(assigned_numbers),
            "missing_asset_count": len(missing_assets),
            "assets_checked": not options["skip_assets"],
        }

        mismatches = {}
        expected_values = {
            "customer_count": options["expect_customers"],
            "token_count": options["expect_tokens"],
            "user_count": options["expect_users"],
        }
        for key, expected_value in expected_values.items():
            if expected_value is not None and result[key] != expected_value:
                mismatches[key] = {"expected": expected_value, "actual": result[key]}

        has_errors = any(
            (
                duplicate_count,
                invalid_code_count,
                out_of_range_count,
                len(missing_assets),
                len(mismatches),
            )
        )
        if has_errors:
            result["status"] = "error"
        if mismatches:
            result["count_mismatches"] = mismatches
        if missing_assets:
            result["missing_asset_examples"] = missing_assets[:10]

        if options["as_json"]:
            self.stdout.write(json.dumps(result, sort_keys=True))
        else:
            summary = " ".join(f"{key}={value}" for key, value in result.items())
            self.stdout.write(f"legacy_inventory_preflight {summary}")

        if has_errors:
            raise CommandError("Legacy inventory preflight failed; no data was changed.")
