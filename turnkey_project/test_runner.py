"""Test runner that prevents accidental external side effects."""

from unittest.mock import patch

from django.test import override_settings
from django.test.runner import DiscoverRunner


def _blocked_external_call(*args, **kwargs):
    raise AssertionError(
        "External HTTP/SMTP calls are blocked during tests. Mock the integration boundary."
    )


class NoExternalCallsDiscoverRunner(DiscoverRunner):
    def setup_test_environment(self, **kwargs):
        super().setup_test_environment(**kwargs)
        self._email_override = override_settings(
            EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
            DOTYKACKA_AUTHORIZATION_TOKEN="",
            DOTYKACKA_CLOUD_ID=0,
            DOTYKACKA_DISCOUNT_GROUP_ID=0,
            BREVO_API_KEY="",
            BREVO_LIST_ID=0,
            GOOGLE_WALLET_ISSUER_ID="",
            GOOGLE_WALLET_CLASS_SUFFIX="MB",
        )
        self._email_override.enable()
        self._external_patchers = [
            patch("requests.sessions.Session.request", side_effect=_blocked_external_call),
            patch("urllib3.PoolManager.request", side_effect=_blocked_external_call),
            patch("smtplib.SMTP", side_effect=_blocked_external_call),
            patch("smtplib.SMTP_SSL", side_effect=_blocked_external_call),
        ]
        for patcher in self._external_patchers:
            patcher.start()

    def teardown_test_environment(self, **kwargs):
        for patcher in reversed(self._external_patchers):
            patcher.stop()
        self._email_override.disable()
        super().teardown_test_environment(**kwargs)
