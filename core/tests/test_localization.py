import re
from pathlib import Path

from django.conf import settings
from django.template import Engine, TemplateSyntaxError
from django.test import SimpleTestCase
from django.urls import resolve, reverse
from django.utils import translation

from billing.models import PlanVersion
from enrollment.models import EnrollmentFollowUp
from integrations.models import IntegrationJob
from printing.models import PrintRequest


class LocalizationConfigurationTests(SimpleTestCase):
    def test_polish_is_the_only_enabled_launch_language(self):
        self.assertEqual(settings.LANGUAGE_CODE, "pl")
        self.assertEqual([code for code, _name in settings.LANGUAGES], ["pl"])
        self.assertEqual(settings.LOCALE_PATHS, [Path(settings.BASE_DIR) / "locale"])

    def test_locale_middleware_runs_after_sessions(self):
        sessions = settings.MIDDLEWARE.index(
            "django.contrib.sessions.middleware.SessionMiddleware"
        )
        locale = settings.MIDDLEWARE.index("django.middleware.locale.LocaleMiddleware")
        common = settings.MIDDLEWARE.index("django.middleware.common.CommonMiddleware")
        self.assertLess(sessions, locale)
        self.assertLess(locale, common)

    def test_standard_language_endpoint_is_available_for_future_catalogs(self):
        route = resolve(reverse("set_language"))
        self.assertEqual(route.func.__module__, "django.views.i18n")

    def test_unsupported_browser_language_keeps_the_interface_polish(self):
        response = self.client.get(reverse("login"), HTTP_ACCEPT_LANGUAGE="en")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Content-Language"], "pl")
        self.assertContains(response, '<html lang="pl"', html=False)
        self.assertContains(response, "Zaloguj się")
        self.assertNotContains(response, ">Username<")

    def test_user_visible_choice_and_workflow_labels_are_polish(self):
        with translation.override("pl"):
            self.assertEqual(str(PrintRequest.Status.SUBMITTED.label), "Złożone")
            self.assertEqual(str(IntegrationJob.Status.PENDING.label), "Oczekuje")
            self.assertEqual(str(PlanVersion.BillingInterval.MONTHLY.label), "Miesięcznie")
            followup = EnrollmentFollowUp(kind="wallet.apple.issue")
            self.assertEqual(followup.get_kind_display(), "Wydanie karty Apple Wallet")


class LocalizableTemplateTests(SimpleTestCase):
    load_i18n_pattern = re.compile(r"{%-?\s*load\s+[^%]*\bi18n\b[^%]*%}")
    blocktranslate_pattern = re.compile(
        r"{%\s*blocktranslate(?P<options>[^%]*)%}(?P<body>.*?){%\s*endblocktranslate\s*%}",
        re.DOTALL,
    )
    template_variable_pattern = re.compile(r"{{\s*(?P<expression>.*?)\s*}}")

    @classmethod
    def active_template_paths(cls):
        base_dir = Path(settings.BASE_DIR)
        paths = set((base_dir / "templates").glob("**/*.html"))
        paths.update(base_dir.glob("*/templates/**/*.html"))
        return sorted(
            path
            for path in paths
            if "turnkey_app" not in path.parts and "staticfiles" not in path.parts
        )

    def test_every_active_template_loads_translation_tags(self):
        missing = []
        for path in self.active_template_paths():
            source = path.read_text(encoding="utf-8")
            if not self.load_i18n_pattern.search(source):
                missing.append(str(path.relative_to(settings.BASE_DIR)))
        self.assertEqual(missing, [])

    def test_every_active_template_has_valid_django_syntax(self):
        engine = Engine.get_default()
        failures = []
        for path in self.active_template_paths():
            try:
                engine.from_string(path.read_text(encoding="utf-8"))
            except TemplateSyntaxError as exc:
                failures.append(f"{path.relative_to(settings.BASE_DIR)}: {exc}")
        self.assertEqual(failures, [])

    def test_nested_blocktranslate_values_use_explicit_aliases(self):
        failures = []
        for path in self.active_template_paths():
            source = path.read_text(encoding="utf-8")
            for block in self.blocktranslate_pattern.finditer(source):
                if re.search(r"\bwith\b", block.group("options")):
                    continue
                expressions = [
                    variable.group("expression")
                    for variable in self.template_variable_pattern.finditer(
                        block.group("body")
                    )
                ]
                if any("." in expression or "|" in expression for expression in expressions):
                    failures.append(str(path.relative_to(settings.BASE_DIR)))
                    break
        self.assertEqual(failures, [])
