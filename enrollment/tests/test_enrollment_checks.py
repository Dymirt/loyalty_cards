from django.core.checks import run_checks
from django.test import SimpleTestCase, override_settings


class EnrollmentDeploymentCheckTests(SimpleTestCase):
    @override_settings(ENROLLMENT_LINK_TTL_DAYS=0)
    def test_link_lifetime_must_be_positive(self):
        errors = run_checks(tags=["security"])

        self.assertIn("enrollment.E001", {error.id for error in errors})
