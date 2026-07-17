import base64
import hashlib
import json

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.db import migrations


PREFIX = "fernet:v1:"


def _configured_keys():
    configured = getattr(settings, "TENANT_SECRETS_ENCRYPTION_KEYS", [])
    if configured:
        return [key.encode("ascii") for key in configured]
    digest = hashlib.sha256(settings.SECRET_KEY.encode("utf-8")).digest()
    return [base64.urlsafe_b64encode(digest)]


def _decrypt(encrypted_value):
    if not encrypted_value:
        return {}
    if not encrypted_value.startswith(PREFIX):
        raise RuntimeError("Unsupported tenant credential format during migration.")
    token = encrypted_value.removeprefix(PREFIX).encode("ascii")
    for key in _configured_keys():
        try:
            payload = Fernet(key).decrypt(token)
        except InvalidToken:
            continue
        return json.loads(payload.decode("utf-8"))
    raise RuntimeError("Tenant credentials cannot be decrypted during migration.")


def _encrypt(credentials):
    cleaned = {key: value for key, value in credentials.items() if value}
    if not cleaned:
        return ""
    payload = json.dumps(cleaned, sort_keys=True).encode("utf-8")
    token = Fernet(_configured_keys()[0]).encrypt(payload).decode("ascii")
    return f"{PREFIX}{token}"


def promote_legacy_authorization_to_refresh_token(apps, schema_editor):
    IntegrationConnection = apps.get_model("dotykacka", "IntegrationConnection")
    for connection in IntegrationConnection.objects.filter(provider="dotykacka"):
        credentials = _decrypt(connection.credentials_encrypted)
        legacy_token = credentials.get("authorization_token")
        if not legacy_token or credentials.get("refresh_token"):
            continue
        credentials["refresh_token"] = (
            legacy_token.removeprefix("User ").strip()
        )
        connection.credentials_encrypted = _encrypt(credentials)
        connection.save(update_fields=("credentials_encrypted",))


class Migration(migrations.Migration):
    dependencies = [("dotykacka", "0013_backfill_card_designs")]

    operations = [
        migrations.RunPython(
            promote_legacy_authorization_to_refresh_token,
            reverse_code=migrations.RunPython.noop,
        )
    ]
