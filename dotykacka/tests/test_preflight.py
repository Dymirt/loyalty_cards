from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from dotykacka.management.commands.preflight_legacy_inventory import expected_asset_paths
from dotykacka.models import AccessToken, Klient

from .base import create_klient, create_superuser


class LegacyInventoryPreflightTests(TestCase):
    @staticmethod
    def create_assets(media_root: Path, start: int, end: int):
        for number in range(start, end + 1):
            for path in expected_asset_paths(media_root, "MB", number):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()

    def test_reports_aggregates_without_changing_database(self):
        create_superuser()
        create_klient("MB-1")
        AccessToken.objects.create(token="test-token")
        with TemporaryDirectory() as directory:
            self.create_assets(Path(directory), 1, 2)
            output = StringIO()
            call_command(
                "preflight_legacy_inventory",
                media_root=directory,
                start=1,
                end=2,
                expect_customers=1,
                expect_tokens=1,
                expect_users=1,
                as_json=True,
                stdout=output,
            )

        result = json.loads(output.getvalue())
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["assigned_card_count"], 1)
        self.assertEqual(result["available_card_count"], 1)
        self.assertEqual(Klient.objects.count(), 1)
        self.assertEqual(AccessToken.objects.count(), 1)

    def test_missing_asset_fails_without_data_changes(self):
        create_klient("MB-1")
        with TemporaryDirectory() as directory, self.assertRaises(CommandError):
            call_command(
                "preflight_legacy_inventory",
                media_root=directory,
                start=1,
                end=1,
                stdout=StringIO(),
            )
        self.assertEqual(Klient.objects.count(), 1)

    def test_malformed_database_code_is_reported(self):
        create_klient("NOT-A-CARD")
        with self.assertRaises(CommandError):
            call_command(
                "preflight_legacy_inventory",
                start=1,
                end=1,
                skip_assets=True,
                stdout=StringIO(),
            )
