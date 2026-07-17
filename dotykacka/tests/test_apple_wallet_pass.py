import json
from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import TestCase, override_settings

from dotykacka.services.apple_wallet import apple_pass_payload, generate_manifest
from dotykacka.services.wallets import wallet_identity

from .base import create_klient


class AppleWalletPassTests(TestCase):
    def test_manifest_hashes_payload_and_excludes_signing_material(self):
        with TemporaryDirectory() as directory:
            pass_dir = Path(directory)
            (pass_dir / "pass.json").write_text('{"formatVersion": 1}', encoding="utf-8")
            (pass_dir / "certificate.pem").write_text("secret", encoding="utf-8")

            generate_manifest(pass_dir)

            manifest = json.loads((pass_dir / "manifest.json").read_text(encoding="utf-8"))
        self.assertIn("pass.json", manifest)
        self.assertNotIn("certificate.pem", manifest)

    @override_settings(
        APPLE_WALLET_PASS_TYPE_IDENTIFIER="pass.example.test",
        APPLE_WALLET_TEAM_IDENTIFIER="TEAM123",
    )
    def test_payload_uses_stable_wallet_identity_and_tenant_brand(self):
        customer = create_klient("MB-7")
        wallet = wallet_identity(customer)
        design = customer.tenant.card_designs.first()

        first = apple_pass_payload(customer=customer, wallet=wallet, design=design)
        second = apple_pass_payload(customer=customer, wallet=wallet, design=design)

        self.assertEqual(first, second)
        self.assertEqual(first["passTypeIdentifier"], "pass.example.test")
        self.assertEqual(first["teamIdentifier"], "TEAM123")
        self.assertEqual(first["serialNumber"], str(wallet.apple_serial))
        self.assertEqual(first["barcode"]["message"], "MB-7")
        self.assertEqual(first["organizationName"], "Atelier-Café Marta Banaszek")
