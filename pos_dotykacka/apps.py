from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class PosDotykackaConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "pos_dotykacka"
    verbose_name = "Dotykačka POS"

    def ready(self):
        from integrations.registry import (
            SettingsProvider,
            SystemConnectionCheck,
            register_settings_provider,
            register_system_connection_check,
        )

        from .forms import DotykackaIntegrationForm
        from .services import (
            connector_system_check,
            tenant_connections_system_check,
            test_connection,
        )

        from . import jobs  # noqa: F401

        register_settings_provider(
            SettingsProvider(
                provider="dotykacka",
                title="Dotykačka",
                description=_("Synchronizacja klientów i grupy rabatowej tej firmy."),
                form_class=DotykackaIntegrationForm,
                tester=test_connection,
                secret_name="refresh_token",
                secret_label=_("Autoryzacja Connector"),
                tenant_testable=False,
            )
        )
        register_system_connection_check(
            SystemConnectionCheck(
                key="dotykacka-connector",
                title="Dotykačka Connector",
                description=_(
                    "Platformowy client ID i sekret używane do bezpiecznego podłączania firm."
                ),
                checker=connector_system_check,
            )
        )
        register_system_connection_check(
            SystemConnectionCheck(
                key="dotykacka-tenants",
                title=_("Dotykačka API — chmury firm"),
                description=_(
                    "Zaszyfrowany Refresh Token każdej firmy jest wymieniany z jej Cloud ID na krótkotrwały token dostępu."
                ),
                checker=tenant_connections_system_check,
            )
        )
