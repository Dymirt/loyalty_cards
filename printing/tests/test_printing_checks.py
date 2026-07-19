from django.core.checks import run_checks
from django.test import SimpleTestCase, override_settings


class PrintingDeploymentCheckTests(SimpleTestCase):
    @override_settings(
        MEDIA_ROOT="/tmp/loyalty-public-media",
        STATIC_ROOT="/tmp/loyalty-public-static",
        PRINT_PACKAGE_ROOT="/tmp/loyalty-protected-printing",
    )
    def test_protected_root_outside_public_roots_passes(self):
        self.assertFalse(
            [error for error in run_checks() if error.id == "printing.E001"]
        )

    @override_settings(
        MEDIA_ROOT="/tmp/loyalty-public-media",
        STATIC_ROOT="/tmp/loyalty-public-static",
        PRINT_PACKAGE_ROOT="/tmp/loyalty-public-media/printing",
    )
    def test_package_root_below_media_is_rejected(self):
        errors = [error for error in run_checks() if error.id == "printing.E001"]
        self.assertEqual(len(errors), 1)
        self.assertIn("MEDIA_ROOT", errors[0].msg)
