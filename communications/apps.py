from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class CommunicationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "communications"
    verbose_name = _("Komunikacja")

    def ready(self):
        from integrations.registry import (
            SettingsProvider,
            SystemConnectionCheck,
            register_settings_provider,
            register_system_connection_check,
        )

        from .ai import test_openai_connection
        from .forms import OpenAIIntegrationForm
        from .services import smtp_system_check
        from . import jobs  # noqa: F401

        register_settings_provider(
            SettingsProvider(
                provider="openai",
                title="OpenAI",
                description=_(
                    "Generator treści i stylu kampanii e-mail z kluczem API należącym do tej firmy."
                ),
                form_class=OpenAIIntegrationForm,
                tester=test_openai_connection,
                secret_name="api_key",
                secret_label=_("Klucz API OpenAI"),
            )
        )

        register_system_connection_check(
            SystemConnectionCheck(
                key="smtp",
                title="SMTP",
                description=_(
                    "Logowanie do serwera pocztowego bez wysyłania wiadomości testowej."
                ),
                checker=smtp_system_check,
            )
        )
