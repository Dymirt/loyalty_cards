from django.conf import settings
from django.test import SimpleTestCase

from loyalty_platform.test_runner import _blocked_external_call


class ExternalCallGuardTests(SimpleTestCase):
    def test_project_uses_external_call_blocking_runner(self):
        self.assertEqual(
            settings.TEST_RUNNER,
            "loyalty_platform.test_runner.NoExternalCallsDiscoverRunner",
        )

    def test_guard_requires_integrations_to_be_mocked(self):
        with self.assertRaises(AssertionError):
            _blocked_external_call()
