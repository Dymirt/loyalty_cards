import importlib
from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.test import SimpleTestCase
from django.urls import reverse

from core.architecture import TARGET_APPS, forbidden_imports
from loyalty_platform.configuration import config_with_legacy_alias


class PhaseFourArchitectureTests(SimpleTestCase):
    def test_active_project_package_is_loyalty_platform(self):
        self.assertEqual(settings.ROOT_URLCONF, "loyalty_platform.urls")
        self.assertEqual(
            settings.WSGI_APPLICATION,
            "loyalty_platform.wsgi.application",
        )
        self.assertEqual(
            settings.ASGI_APPLICATION,
            "loyalty_platform.asgi.application",
        )
        self.assertEqual(
            settings.TEST_RUNNER,
            "loyalty_platform.test_runner.NoExternalCallsDiscoverRunner",
        )

    def test_legacy_project_imports_are_compatibility_shims(self):
        legacy_settings = importlib.import_module("turnkey_project.settings")
        legacy_urls = importlib.import_module("turnkey_project.urls")
        legacy_runner = importlib.import_module("turnkey_project.test_runner")
        legacy_asgi = importlib.import_module("turnkey_project.asgi")
        legacy_wsgi = importlib.import_module("turnkey_project.wsgi")
        active_urls = importlib.import_module("loyalty_platform.urls")
        active_runner = importlib.import_module("loyalty_platform.test_runner")
        active_asgi = importlib.import_module("loyalty_platform.asgi")
        active_wsgi = importlib.import_module("loyalty_platform.wsgi")

        self.assertEqual(legacy_settings.ROOT_URLCONF, settings.ROOT_URLCONF)
        self.assertIs(legacy_urls.urlpatterns, active_urls.urlpatterns)
        self.assertIs(
            legacy_runner.NoExternalCallsDiscoverRunner,
            active_runner.NoExternalCallsDiscoverRunner,
        )
        self.assertIs(legacy_asgi.application, active_asgi.application)
        self.assertIs(legacy_wsgi.application, active_wsgi.application)

    def test_destination_apps_are_installed_namespaced_and_model_free(self):
        for app_name in TARGET_APPS:
            with self.subTest(app=app_name):
                app_config = apps.get_app_config(app_name)
                self.assertEqual(app_config.name, app_name)
                urlconf = importlib.import_module(f"{app_name}.urls")
                self.assertEqual(urlconf.app_name, app_name)
                self.assertIsInstance(urlconf.urlpatterns, list)
                self.assertEqual(list(app_config.get_models()), [])

    def test_new_apps_obey_declared_dependency_direction(self):
        violations = forbidden_imports(Path(settings.BASE_DIR))
        self.assertEqual(violations, [])

    def test_new_allowed_hosts_setting_precedes_legacy_fallback(self):
        class FakeConfig:
            def __init__(self, values):
                self.values = values

            def __call__(self, name, default=""):
                return self.values.get(name, default)

        self.assertEqual(
            config_with_legacy_alias(
                FakeConfig(
                    {
                        "LOYALTY_ALLOWED_HOSTS_FILE": "/new/path",
                        "TURNKEY_ALLOWED_HOSTS_FILE": "/old/path",
                    }
                ),
                "LOYALTY_ALLOWED_HOSTS_FILE",
                "TURNKEY_ALLOWED_HOSTS_FILE",
                default="/default/path",
            ),
            "/new/path",
        )
        self.assertEqual(
            config_with_legacy_alias(
                FakeConfig({"TURNKEY_ALLOWED_HOSTS_FILE": "/old/path"}),
                "LOYALTY_ALLOWED_HOSTS_FILE",
                "TURNKEY_ALLOWED_HOSTS_FILE",
                default="/default/path",
            ),
            "/old/path",
        )

    def test_legacy_turnkey_route_redirects_through_marketing_namespace(self):
        response = self.client.get(reverse("turnkey_compat:index"))
        self.assertRedirects(
            response,
            reverse("marketing:home"),
            fetch_redirect_response=False,
        )
