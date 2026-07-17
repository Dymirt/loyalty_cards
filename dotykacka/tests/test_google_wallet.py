import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase, override_settings

from dotykacka.google_wallet.JWT import get_wallet_url


class GoogleWalletJwtTests(SimpleTestCase):
    def test_missing_service_account_file_is_rejected(self):
        with override_settings(
            GOOGLE_WALLET_SERVICE_ACCOUNT_FILE=Path("/missing/test-service-account.json"),
        ), self.assertRaises(ImproperlyConfigured):
            get_wallet_url(
                "Test Customer", "MB-12", issuer_id="issuer", class_suffix="MB"
            )

    @patch("dotykacka.google_wallet.JWT.jwt.encode", return_value="signed-token")
    @patch("dotykacka.google_wallet.JWT.serialization.load_pem_private_key")
    def test_claims_are_tenant_baseline_compatible(self, load_key, encode):
        with TemporaryDirectory() as directory:
            keyfile = Path(directory) / "service-account.json"
            keyfile.write_text(
                json.dumps(
                    {
                        "client_email": "wallet@example.test",
                        "private_key": "test-private-key",
                    }
                ),
                encoding="utf-8",
            )
            load_key.return_value = object()
            with override_settings(
                GOOGLE_WALLET_SERVICE_ACCOUNT_FILE=keyfile,
                GOOGLE_WALLET_SERVICE_ACCOUNT_EMAIL="",
                GOOGLE_WALLET_ORIGINS=["https://club.example.test"],
            ):
                result = get_wallet_url(
                    "Test Customer",
                    "MB-12",
                    issuer_id="issuer123",
                    class_suffix="MB",
                    customer_image_url="https://club.example.test/media/card.jpg",
                )

        self.assertEqual(result, "https://pay.google.com/gp/v/save/signed-token")
        claims = encode.call_args.args[0]
        loyalty_object = claims["payload"]["loyaltyObjects"][0]
        self.assertEqual(loyalty_object["id"], "issuer123.MB-12")
        self.assertEqual(loyalty_object["classId"], "issuer123.MB")
        self.assertEqual(loyalty_object["barcode"]["value"], "MB-12")
        self.assertEqual(claims["origins"], ["https://club.example.test"])
