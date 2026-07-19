from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class BrevoConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "brevo"
    verbose_name = "Brevo"

    def ready(self):
        from integrations.registry import (
            SettingsProvider,
            SystemConnectionCheck,
            register_settings_provider,
            register_system_connection_check,
        )

        from .forms import BrevoIntegrationForm
        from .services import system_connection_check, test_connection

        from . import jobs  # noqa: F401

        register_settings_provider(
            SettingsProvider(
                provider="brevo",
                title="Brevo",
                description=_("Lista kontaktów i klucz API należące do tej firmy."),
                form_class=BrevoIntegrationForm,
                tester=test_connection,
                secret_name="api_key",
                secret_label=_("Klucz API"),
            )
        )
        register_system_connection_check(
            SystemConnectionCheck(
                key="brevo-tenants",
                title=_("Brevo — połączenia firm"),
                description=_(
                    "Dostęp do konta Brevo z kluczy API zapisanych oddzielnie dla aktywnych firm."
                ),
                checker=system_connection_check,
            )
        )
