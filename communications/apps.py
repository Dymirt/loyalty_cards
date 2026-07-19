from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class CommunicationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "communications"
    verbose_name = _("Komunikacja")

    def ready(self):
        from integrations.registry import (
            SystemConnectionCheck,
            register_system_connection_check,
        )

        from .services import smtp_system_check
        from . import jobs  # noqa: F401

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
