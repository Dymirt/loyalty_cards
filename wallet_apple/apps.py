from django.apps import AppConfig


class WalletAppleConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "wallet_apple"
    verbose_name = "Apple Wallet"

    def ready(self):
        from integrations.registry import (
            SystemConnectionCheck,
            register_system_connection_check,
        )
        from wallets.registry import register_issuer

        from .services import issuer, system_connection_check
        from . import jobs  # noqa: F401

        register_issuer("apple", issuer)
        register_system_connection_check(
            SystemConnectionCheck(
                key="apple-wallet",
                title="Apple Wallet",
                description=(
                    "Identyfikatory platformy, certyfikat, klucz prywatny i certyfikat WWDR."
                ),
                checker=system_connection_check,
            )
        )
