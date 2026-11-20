import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import TestCase, override_settings
from PIL import Image

from cards.services import assign_locked_card
from dotykacka.models import PhysicalCard
from dotykacka.services.apple_wallet import (
    apple_pass_payload,
    build_apple_pass,
    generate_manifest,
)
from dotykacka.services.wallets import wallet_identity

from .base import create_klient, create_physical_card


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

    @override_settings(
        APPLE_WALLET_PASS_TYPE_IDENTIFIER="pass.example.test",
        APPLE_WALLET_TEAM_IDENTIFIER="TEAM123",
    )
    def test_physical_card_front_is_used_as_apple_wallet_strip(self):
        with TemporaryDirectory() as directory:
            with self.settings(
                MEDIA_ROOT=directory,
                APPLE_WALLET_TEMPLATE_DIR=directory,
            ):
                card = create_physical_card(number=12)
                customer = create_klient(card.code)
                assign_locked_card(card=card, customer=customer)
                relative_front = Path("cards/card-12/MB-12_front.jpg")
                front_path = Path(directory) / relative_front
                front_path.parent.mkdir(parents=True)
                Image.new("RGB", (1011, 638), "#D94A64").save(
                    front_path,
                    format="JPEG",
                )
                card.front_image_path = relative_front.as_posix()
                card.save(update_fields=("front_image_path",))
                wallet = wallet_identity(customer, card_design=card.batch.design)

                with patch(
                    "wallet_apple.services.render_card",
                    side_effect=AssertionError("renderer must not replace saved MB front"),
                ), patch("wallet_apple.services.sign_manifest"):
                    pass_path, artifact = build_apple_pass(
                        customer=customer,
                        wallet=wallet,
                        design=card.batch.design,
                    )

                self.assertTrue(pass_path.is_file())
                self.assertEqual(artifact.physical_card, card)

    @override_settings(
        APPLE_WALLET_PASS_TYPE_IDENTIFIER="pass.example.test",
        APPLE_WALLET_TEAM_IDENTIFIER="TEAM123",
    )
    def test_virtual_mb_601_uses_mb_1_front_without_rendering_or_copying_it(self):
        with TemporaryDirectory() as directory:
            with self.settings(
                MEDIA_ROOT=directory,
                APPLE_WALLET_TEMPLATE_DIR=directory,
            ):
                source = create_physical_card(number=1)
                virtual = PhysicalCard(
                    tenant=source.tenant,
                    batch=source.batch,
                    artwork_source=source,
                    code="MB-601",
                    number=601,
                    status=PhysicalCard.Status.AVAILABLE,
                )
                virtual.full_clean()
                virtual.save()
                relative_front = Path("cards/card-1/MB-1_front.jpg")
                front_path = Path(directory) / relative_front
                front_path.parent.mkdir(parents=True)
                Image.new("RGB", (1011, 638), "#D94A64").save(
                    front_path,
                    format="JPEG",
                )
                source.front_image_path = relative_front.as_posix()
                source.save(update_fields=("front_image_path",))
                customer = create_klient(virtual.code)
                assign_locked_card(card=virtual, customer=customer)
                wallet = wallet_identity(customer, card_design=source.batch.design)

                with patch(
                    "wallet_apple.services.render_card",
                    side_effect=AssertionError("renderer must not recreate MB-1 artwork"),
                ), patch("wallet_apple.services.sign_manifest"):
                    pass_path, artifact = build_apple_pass(
                        customer=customer,
                        wallet=wallet,
                        design=source.batch.design,
                    )

                self.assertTrue(pass_path.is_file())
                self.assertEqual(artifact.physical_card, virtual)
                self.assertEqual(virtual.front_image_path, "")
