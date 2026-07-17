from unittest.mock import Mock, patch

from django.test import TestCase
from django.urls import reverse

from integrations.contracts import SystemCheckResult
from integrations.registry import SystemConnectionCheck

from dotykacka.tests.base import create_superuser, create_tenant, create_tenant_owner


class SystemConnectionsViewTests(TestCase):
    def setUp(self):
        self.tenant = create_tenant()
        self.owner = create_tenant_owner(self.tenant)
        self.operator = create_superuser()

    def test_page_is_superuser_only(self):
        url = reverse("integrations:system_connections")
        self.assertEqual(self.client.get(url).status_code, 302)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(url).status_code, 302)

    def test_superuser_sees_registered_system_checks_without_running_them(self):
        checker = Mock(
            return_value=SystemCheckResult(ok=True, summary="Nie uruchamiaj automatycznie")
        )
        check = SystemConnectionCheck(
            key="safe-test",
            title="Bezpieczny test",
            description="Test bez sekretów.",
            checker=checker,
        )
        self.client.force_login(self.operator)
        with patch.dict(
            "integrations.registry._system_connection_checks",
            {check.key: check},
            clear=True,
        ):
            response = self.client.get(reverse("integrations:system_connections"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Bezpieczny test")
        self.assertContains(response, "Nie testowano w tym widoku")
        checker.assert_not_called()

    def test_dotykacka_onboarding_is_not_on_the_system_page(self):
        self.client.force_login(self.operator)

        response = self.client.get(reverse("integrations:system_connections"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Autoryzacja firm Dotykačka")
        self.assertNotContains(response, "Połącz z Dotykačka")

    def test_superuser_can_run_one_redacted_check(self):
        checker = Mock(
            return_value=SystemCheckResult(
                ok=True,
                summary="Połączenie testowe działa.",
                details=("Bez ujawniania sekretów.",),
            )
        )
        check = SystemConnectionCheck(
            key="safe-test",
            title="Bezpieczny test",
            description="Test bez sekretów.",
            checker=checker,
        )
        self.client.force_login(self.operator)
        with patch.dict(
            "integrations.registry._system_connection_checks",
            {check.key: check},
            clear=True,
        ):
            response = self.client.post(
                reverse("integrations:test_system_connection", args=[check.key]),
                HTTP_HX_REQUEST="true",
            )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Połączenie testowe działa")
        self.assertContains(response, "Bez ujawniania sekretów")
        checker.assert_called_once_with()

    def test_test_all_runs_every_registered_check(self):
        first = Mock(return_value=SystemCheckResult(ok=True, summary="Pierwszy OK"))
        second = Mock(return_value=SystemCheckResult(ok=False, summary="Drugi błąd"))
        checks = {
            "first": SystemConnectionCheck("first", "Pierwszy", "Opis", first),
            "second": SystemConnectionCheck("second", "Drugi", "Opis", second),
        }
        self.client.force_login(self.operator)
        with patch.dict(
            "integrations.registry._system_connection_checks", checks, clear=True
        ):
            response = self.client.post(
                reverse("integrations:test_system_connection", args=["all"])
            )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Pierwszy OK")
        self.assertContains(response, "Drugi błąd")
        first.assert_called_once_with()
        second.assert_called_once_with()

    def test_provider_exception_message_is_not_exposed(self):
        checker = Mock(side_effect=RuntimeError("secret-token-must-not-render"))
        check = SystemConnectionCheck(
            key="safe-test",
            title="Bezpieczny test",
            description="Test bez sekretów.",
            checker=checker,
        )
        self.client.force_login(self.operator)
        with patch.dict(
            "integrations.registry._system_connection_checks",
            {check.key: check},
            clear=True,
        ):
            response = self.client.post(
                reverse("integrations:test_system_connection", args=[check.key])
            )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Kod błędu: RuntimeError")
        self.assertNotContains(response, "secret-token-must-not-render")
