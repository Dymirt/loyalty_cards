"""Versioned encryption for tenant-owned integration credentials."""

import base64
import hashlib
import json

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


_PREFIX = "fernet:v1:"


def _configured_keys() -> list[bytes]:
    configured = getattr(settings, "TENANT_SECRETS_ENCRYPTION_KEYS", [])
    if configured:
        return [key.encode("ascii") for key in configured]
    # Compatibility fallback for already-migrated Marta data. Production must
    # configure a dedicated key before DJANGO_SECRET_KEY rotation.
    digest = hashlib.sha256(settings.SECRET_KEY.encode("utf-8")).digest()
    return [base64.urlsafe_b64encode(digest)]


def encrypt_credentials(credentials: dict[str, str]) -> str:
    cleaned = {key: value for key, value in credentials.items() if value}
    if not cleaned:
        return ""
    payload = json.dumps(cleaned, sort_keys=True).encode("utf-8")
    token = Fernet(_configured_keys()[0]).encrypt(payload).decode("ascii")
    return f"{_PREFIX}{token}"


def decrypt_credentials(encrypted_value: str) -> dict[str, str]:
    if not encrypted_value:
        return {}
    if not encrypted_value.startswith(_PREFIX):
        raise ImproperlyConfigured("Unsupported tenant credential format.")
    token = encrypted_value.removeprefix(_PREFIX).encode("ascii")
    for key in _configured_keys():
        try:
            payload = Fernet(key).decrypt(token)
        except InvalidToken:
            continue
        return json.loads(payload.decode("utf-8"))
    raise ImproperlyConfigured(
        "Tenant credentials cannot be decrypted with configured keys."
    )


__all__ = ["decrypt_credentials", "encrypt_credentials"]
