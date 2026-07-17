import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from dotykacka import apple_wallet_pass


class AppleWalletPassTests(SimpleTestCase):
    def test_manifest_hashes_payload_and_excludes_signing_material(self):
        with TemporaryDirectory() as directory:
            pass_dir = Path(directory)
            (pass_dir / "pass.json").write_text('{"formatVersion": 1}', encoding="utf-8")
            (pass_dir / "certificate.pem").write_text("secret", encoding="utf-8")

            apple_wallet_pass.generate_manifest(str(pass_dir))

            manifest = json.loads((pass_dir / "manifest.json").read_text(encoding="utf-8"))
        self.assertIn("pass.json", manifest)
        self.assertNotIn("certificate.pem", manifest)

    @override_settings(
        APPLE_WALLET_PASS_TYPE_IDENTIFIER="pass.example.test",
        APPLE_WALLET_TEAM_IDENTIFIER="TEAM123",
    )
    @patch("dotykacka.apple_wallet_pass.shutil.rmtree")
    @patch("dotykacka.apple_wallet_pass.subprocess.run")
    @patch("dotykacka.apple_wallet_pass.sign_manifest")
    def test_build_pass_contains_expected_stable_card_value(
        self, sign_manifest, subprocess_run, rmtree
    ):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            template_dir = root / "template"
            output_dir = root / "output"
            crop_dir = root / "crops"
            template_dir.mkdir()
            output_dir.mkdir()
            crop_dir.mkdir()
            for filename in ("icon.png", "icon@2x.png", "logo@2x.png"):
                (template_dir / filename).write_bytes(b"asset")
            (crop_dir / "cropped_image_7.jpg").write_bytes(b"crop")

            with patch.multiple(
                apple_wallet_pass,
                TEMPLATE_DIR=str(template_dir),
                OUTPUT_DIR=str(output_dir),
                CROPED_IMG_DIR=str(crop_dir),
            ):
                result = apple_wallet_pass.build_pass(7)
                pass_data = json.loads(
                    (output_dir / "pass_7" / "pass.json").read_text(encoding="utf-8")
                )

        self.assertEqual(result, str(output_dir / "pass_7.pkpass"))
        self.assertEqual(pass_data["passTypeIdentifier"], "pass.example.test")
        self.assertEqual(pass_data["teamIdentifier"], "TEAM123")
        self.assertEqual(pass_data["barcode"]["message"], "MB-7")
        self.assertEqual(pass_data["storeCard"]["headerFields"][0]["value"], "MB-7")
        sign_manifest.assert_called_once()
        self.assertEqual(subprocess_run.call_args.args[0][0:2], ["zip", "-j"])
        rmtree.assert_called_once()
