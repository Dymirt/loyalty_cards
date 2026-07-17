from django.apps import AppConfig


class WalletGoogleConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "wallet_google"
    verbose_name = "Google Wallet"

    def ready(self):
        from integrations.registry import (
            SettingsProvider,
            SystemConnectionCheck,
            register_settings_provider,
            register_system_connection_check,
        )
        from wallets.registry import register_issuer

        from .forms import GoogleWalletIntegrationForm
        from .services import issuer, system_connection_check
        from . import jobs  # noqa: F401

        register_issuer("google", issuer)
        register_settings_provider(
            SettingsProvider(
                provider="google_wallet",
                title="Google Wallet",
                description=(
                    "Karty korzystają z centralnego wydawcy platformy; klasa, treść i wygląd są dobierane automatycznie dla firmy."
                ),
                form_class=GoogleWalletIntegrationForm,
                tenant_testable=False,
            )
        )
        register_system_connection_check(
            SystemConnectionCheck(
                key="google-wallet",
                title="Google Wallet",
                description=(
                    "Konto usługi, centralny ID wydawcy i odczyt API Google Wallet."
                ),
                checker=system_connection_check,
            )
        )
