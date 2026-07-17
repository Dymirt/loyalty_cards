from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import TestCase, override_settings

from dotykacka.services.wallets import (
    ensure_apple_wallet_pass,
    generate_google_wallet_for_klient,
)

from .base import configure_google_wallet, create_klient


class WalletServiceTests(TestCase):
    @patch("dotykacka.services.wallets.build_pass")
    def test_existing_apple_pass_is_never_overwritten(self, build_pass):
        with TemporaryDirectory() as directory, override_settings(MEDIA_ROOT=directory):
            klient = create_klient("MB-12")
            pass_path = Path(directory) / "output_passes" / "pass_12.pkpass"
            pass_path.parent.mkdir(parents=True)
            pass_path.write_bytes(b"legacy-pass")

            self.assertEqual(ensure_apple_wallet_pass(klient), pass_path)
            self.assertEqual(pass_path.read_bytes(), b"legacy-pass")
            build_pass.assert_not_called()

    @patch("dotykacka.services.wallets.build_pass")
    def test_missing_apple_pass_is_generated_explicitly(self, build_pass):
        with TemporaryDirectory() as directory, override_settings(MEDIA_ROOT=directory):
            klient = create_klient("MB-12")
            generated = Path(directory) / "output_passes" / "pass_12.pkpass"
            build_pass.return_value = str(generated)
            self.assertEqual(ensure_apple_wallet_pass(klient), generated)
            build_pass.assert_called_once_with(12)

    @override_settings(APP_BASE_URL="https://club.example.test")
    @patch("dotykacka.services.wallets.get_wallet_url", return_value="https://wallet.test/save")
    def test_google_wallet_url_is_generated_and_saved(self, get_wallet_url):
        klient = create_klient("MB-12", google_jwt_url="")
        configure_google_wallet(klient.tenant)
        result = generate_google_wallet_for_klient(klient)
        klient.refresh_from_db()

        self.assertEqual(result, "https://wallet.test/save")
        self.assertEqual(klient.google_jwt_url, result)
        get_wallet_url.assert_called_once_with(
            name="Test Customer",
            customer_id="MB-12",
            issuer_id="issuer123",
            class_suffix="MB",
            customer_image_url=(
                "https://club.example.test/media/cropped_images/cropped_image_12.jpg"
            ),
        )
