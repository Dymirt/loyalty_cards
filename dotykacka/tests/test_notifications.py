from pathlib import Path
from tempfile import TemporaryDirectory

from django.core import mail
from django.test import TestCase, override_settings

from dotykacka.services.notifications import send_pass_email

from .base import create_klient


class PassEmailTests(TestCase):
    def test_sends_existing_pass_with_wallet_links(self):
        with TemporaryDirectory() as directory, override_settings(
            MEDIA_ROOT=directory,
            APP_BASE_URL="https://club.example.test",
            DEFAULT_FROM_EMAIL="club@example.test",
        ):
            klient = create_klient("MB-12")
            pass_path = Path(directory) / "output_passes" / "pass_12.pkpass"
            pass_path.parent.mkdir(parents=True)
            pass_path.write_bytes(b"signed-pass")

            sent = send_pass_email(klient)

        self.assertEqual(sent, 1)
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.to, ["customer@example.test"])
        self.assertIn("https://wallet.example.test/save", message.body)
        self.assertEqual(message.attachments[0].filename, "loyalty-card.pkpass")
        self.assertEqual(message.attachments[0].content, b"signed-pass")

    def test_does_not_generate_or_send_when_pass_is_missing(self):
        with TemporaryDirectory() as directory, override_settings(MEDIA_ROOT=directory):
            klient = create_klient("MB-12")
            with self.assertRaises(FileNotFoundError):
                send_pass_email(klient)
        self.assertEqual(len(mail.outbox), 0)

    def test_customer_without_email_is_rejected(self):
        klient = create_klient("MB-12", email=None)
        with self.assertRaises(ValueError):
            send_pass_email(klient)
