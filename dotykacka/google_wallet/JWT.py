"""Deprecated, patch-compatible Google Wallet JWT adapter."""

import jwt
from cryptography.hazmat.primitives import serialization

from wallet_google.services import get_wallet_url as _get_wallet_url


def get_wallet_url(*args, **kwargs):
    return _get_wallet_url(
        *args,
        _jwt=jwt,
        _serialization=serialization,
        **kwargs,
    )


__all__ = ["get_wallet_url"]
