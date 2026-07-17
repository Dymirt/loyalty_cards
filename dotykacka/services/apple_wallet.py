"""Deprecated Apple Wallet imports from the extracted provider."""

from wallet_apple.services import (
    apple_pass_payload,
    build_apple_pass,
    generate_manifest,
    sign_manifest,
    update_wallet_apple_artifact,
)

__all__ = [
    "apple_pass_payload",
    "build_apple_pass",
    "generate_manifest",
    "sign_manifest",
    "update_wallet_apple_artifact",
]
