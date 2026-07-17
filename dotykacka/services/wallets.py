"""Deprecated Wallet orchestration adapters with patch-compatible hooks."""

from wallet_apple.services import build_apple_pass, update_wallet_apple_artifact
from wallet_google.services import get_wallet_url
from wallets.services import (
    apple_pass_path,
    issue_apple,
    issue_google,
    wallet_identity,
)


def ensure_apple_wallet_pass(klient, *, force=False):
    return issue_apple(
        klient,
        force=force,
        builder=build_apple_pass,
        updater=update_wallet_apple_artifact,
    )


def generate_google_wallet_for_klient(klient):
    return issue_google(klient, url_builder=get_wallet_url, remote_sync=False)


__all__ = [
    "apple_pass_path",
    "ensure_apple_wallet_pass",
    "generate_google_wallet_for_klient",
    "wallet_identity",
]
