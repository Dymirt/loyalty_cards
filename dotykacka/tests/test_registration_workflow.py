from unittest.mock import patch

from django.test import TestCase

from dotykacka.services.registration import run_registration_followups

from .base import create_klient


class RegistrationWorkflowTests(TestCase):
    @patch("dotykacka.services.registration.send_pass_email")
    @patch("dotykacka.services.registration.dotykacka_api.register_dotykacka_customer")
    @patch("dotykacka.services.registration.generate_google_wallet_for_klient")
    @patch("dotykacka.services.registration.ensure_apple_wallet_pass")
    def test_runs_wallets_pos_and_email_in_explicit_order(
        self, ensure_apple, generate_google, register_pos, send_email
    ):
        klient = create_klient("MB-12")
        run_registration_followups(klient.pk)
        ensure_apple.assert_called_once()
        generate_google.assert_called_once()
        register_pos.assert_called_once_with(
            "MB-12",
            "Test",
            "Customer",
            "customer@example.test",
            "501234567",
        )
        send_email.assert_called_once()

    @patch("dotykacka.services.registration.send_pass_email")
    @patch("dotykacka.services.registration.dotykacka_api.register_dotykacka_customer")
    @patch(
        "dotykacka.services.registration.generate_google_wallet_for_klient",
        side_effect=RuntimeError("test failure"),
    )
    @patch("dotykacka.services.registration.ensure_apple_wallet_pass")
    def test_wallet_failure_does_not_call_email_but_pos_still_runs(
        self, ensure_apple, generate_google, register_pos, send_email
    ):
        klient = create_klient("MB-12")
        with self.assertLogs("dotykacka.services.registration", level="ERROR"):
            run_registration_followups(klient.pk)
        register_pos.assert_called_once()
        send_email.assert_not_called()
