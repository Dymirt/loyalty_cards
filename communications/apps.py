from django.apps import AppConfig


class CommunicationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "communications"
    verbose_name = "Communications"

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
                description=(
                    "Logowanie do serwera pocztowego bez wysyłania wiadomości testowej."
                ),
                checker=smtp_system_check,
            )
        )
