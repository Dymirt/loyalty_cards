from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from django.test import SimpleTestCase, override_settings

from wallet_apple.services import system_connection_check


class AppleWalletSystemCheckTests(SimpleTestCase):
    pass_type_id = "pass.club.example.test"
    team_id = "TEAM123456"

    def _write_materials(self, directory, *, expires_at, pass_type_id=None):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = x509.Name(
            [
                x509.NameAttribute(
                    NameOID.USER_ID,
                    pass_type_id or self.pass_type_id,
                ),
                x509.NameAttribute(
                    NameOID.ORGANIZATIONAL_UNIT_NAME,
                    self.team_id,
                ),
                x509.NameAttribute(NameOID.COMMON_NAME, "Test Pass Type ID"),
            ]
        )
        certificate = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(subject)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(expires_at - timedelta(days=365))
            .not_valid_after(expires_at)
            .sign(key, hashes.SHA256())
        )
        root = Path(directory)
        certificate_pem = certificate.public_bytes(serialization.Encoding.PEM)
        (root / "certificate.pem").write_bytes(certificate_pem)
        (root / "AppleWWDR.pem").write_bytes(certificate_pem)
        (root / "key.pem").write_bytes(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.TraditionalOpenSSL,
                serialization.NoEncryption(),
            )
        )

    def _check(self, directory):
        with override_settings(
            APPLE_WALLET_TEMPLATE_DIR=directory,
            APPLE_WALLET_PASS_TYPE_IDENTIFIER=self.pass_type_id,
            APPLE_WALLET_TEAM_IDENTIFIER=self.team_id,
        ):
            return system_connection_check()

    def test_expired_certificate_reports_date_and_pass_type(self):
        with TemporaryDirectory() as directory:
            expired_at = datetime(2026, 6, 25, 15, 52, tzinfo=timezone.utc)
            self._write_materials(directory, expires_at=expired_at)

            result = self._check(directory)

        self.assertFalse(result.ok)
        self.assertEqual(result.summary, "Certyfikat Apple Wallet wygasł.")
        self.assertIn(f"Pass Type ID: {self.pass_type_id}", result.details)
        self.assertIn("Certyfikat wygasł: 2026-06-25 15:52 UTC", result.details)

    def test_valid_matching_certificate_passes(self):
        with TemporaryDirectory() as directory:
            self._write_materials(
                directory,
                expires_at=datetime.now(timezone.utc) + timedelta(days=30),
            )

            result = self._check(directory)

        self.assertTrue(result.ok)
        self.assertIn("prawidłowe", result.summary)

    def test_certificate_for_another_pass_type_is_rejected(self):
        with TemporaryDirectory() as directory:
            self._write_materials(
                directory,
                expires_at=datetime.now(timezone.utc) + timedelta(days=30),
                pass_type_id="pass.club.other.test",
            )

            result = self._check(directory)

        self.assertFalse(result.ok)
        self.assertIn("innego Pass Type ID", result.summary)
        self.assertNotIn("pass.club.other.test", " ".join(result.details))
