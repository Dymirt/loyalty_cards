from django.core.checks import run_checks
from django.test import SimpleTestCase, override_settings


class MarketingDeploymentCheckTests(SimpleTestCase):
    @override_settings(
        MARKETING_LEGAL_NAME="",
        MARKETING_CONTACT_EMAIL="not-an-email",
        MARKETING_PRIVACY_VERSION="",
        MARKETING_TERMS_VERSION="",
    )
    def test_public_legal_configuration_is_required(self):
        errors = run_checks(tags=["security"])

        ids = {error.id for error in errors}
        self.assertTrue(
            {"marketing.E001", "marketing.E002", "marketing.E003", "marketing.E004"}
            <= ids
        )
