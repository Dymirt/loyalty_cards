import importlib
from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.test import SimpleTestCase
from django.urls import resolve, reverse

from core.architecture import TARGET_APPS, forbidden_imports
from loyalty_platform.configuration import config_with_legacy_alias


EXTRACTED_MODELS = {
    "billing": {
        "billing.billingperiod",
        "billing.cardpack",
        "billing.cardpackallocation",
        "billing.cardpricetier",
        "billing.entitlementpolicy",
        "billing.plan",
        "billing.planversion",
        "billing.pricebook",
        "billing.pricebookversion",
        "billing.printquoteconsumption",
        "billing.quote",
        "billing.quoteline",
        "billing.tenantsubscription",
        "billing.usageevent",
    },
    "customers": {
        "customers.customerexternalidentity",
        "customers.consentrecord",
    },
    "communications": {"communications.communicationdelivery"},
    "card_artwork": {"card_artwork.cropplan"},
    "integrations": {"integrations.integrationjob"},
    "marketing": {"marketing.marketinglead"},
    "operations": {
        "operations.operationalalert",
        "operations.operationalalertevent",
        "operations.ratelimitbucket",
        "operations.workerheartbeat",
    },
    "pos_dotykacka": {
        "pos_dotykacka.dotykackaconnectstate",
        "pos_dotykacka.dotykackaaccesstoken",
    },
    "printing": {
        "printing.fulfillmentevent",
        "printing.printjob",
        "printing.printpackage",
        "printing.printrequest",
        "printing.printrequestevent",
        "printing.printrun",
        "printing.printruncard",
    },
    "tenants": {"tenants.tenantdomain"},
    "enrollment": {
        "enrollment.enrollment",
        "enrollment.enrollmentaccesslink",
        "enrollment.enrollmentevent",
        "enrollment.enrollmentfollowup",
    },
}


class ExtractedArchitectureTests(SimpleTestCase):
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

    def test_destination_apps_are_installed_namespaced_with_only_planned_models(self):
        for app_name in TARGET_APPS:
            with self.subTest(app=app_name):
                app_config = apps.get_app_config(app_name)
                self.assertEqual(app_config.name, app_name)
                urlconf = importlib.import_module(f"{app_name}.urls")
                self.assertEqual(urlconf.app_name, app_name)
                self.assertIsInstance(urlconf.urlpatterns, list)
                self.assertEqual(
                    {model._meta.label_lower for model in app_config.get_models()},
                    EXTRACTED_MODELS.get(app_name, set()),
                )

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
        self.assertNotIn("turnkey_app", {config.name for config in apps.get_app_configs()})
        active_url_source = (settings.BASE_DIR / "loyalty_platform/urls.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("turnkey_app", active_url_source)
        response = self.client.get(reverse("turnkey_compat:index"))
        self.assertEqual(response.status_code, 301)
        self.assertEqual(response.url, reverse("marketing:home"))
        route = resolve("/turnkey/")
        self.assertEqual(route.func.__module__, "marketing.views")

    def test_legacy_domain_imports_point_to_extracted_owners(self):
        legacy_codes = importlib.import_module("dotykacka.card_codes")
        codes = importlib.import_module("cards.codes")
        legacy_tenancy = importlib.import_module("dotykacka.tenancy")
        authorization = importlib.import_module("tenants.authorization")
        legacy_artwork = importlib.import_module("dotykacka.services.card_designs")
        artwork = importlib.import_module("card_artwork.services")
        legacy_views = importlib.import_module("dotykacka.views")

        self.assertIs(legacy_codes.parse_card_code, codes.parse_card_code)
        self.assertIs(legacy_tenancy.get_public_tenant, authorization.get_public_tenant)
        self.assertIs(legacy_artwork.render_card, artwork.render_card)
        self.assertEqual(legacy_views.tenant_portal.__module__, "tenants.views")
        self.assertEqual(legacy_views.card_design_settings.__module__, "card_artwork.views")

    def test_canonical_and_legacy_urls_use_extracted_views(self):
        routes = (
            ("/dotykacka/c/example/portal", "tenants.views"),
            ("/dotykacka/customers", "customers.views"),
            ("/dotykacka/platform/print-center", "printing.views"),
            ("/dotykacka/c/example/settings/card-design", "card_artwork.views"),
            ("/dotykacka/register", "enrollment.views"),
            ("/dotykacka/c/example/enrollments", "enrollment.views"),
            ("/dotykacka/enrollment/status/example", "enrollment.views"),
        )
        for path, module in routes:
            with self.subTest(path=path):
                self.assertEqual(resolve(path).func.__module__, module)
