import json
import time
from pathlib import Path

import jwt
from cryptography.hazmat.primitives import serialization
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


def get_wallet_url(
    name: str,
    customer_id: str,
    *,
    issuer_id: str,
    class_suffix: str,
    object_id: str = "",
    customer_image_url: str = "",
    image_description: str = "Karta lojalnościowa",
) -> str:
    keyfile = Path(settings.GOOGLE_WALLET_SERVICE_ACCOUNT_FILE)
    if not keyfile.is_file():
        raise ImproperlyConfigured(
            f"Google Wallet service-account file not found: {keyfile}"
        )
    if not issuer_id or not class_suffix:
        raise ImproperlyConfigured("Google Wallet tenant configuration is incomplete")

    service_account = json.loads(keyfile.read_text(encoding="utf-8"))
    service_account_email = (
        settings.GOOGLE_WALLET_SERVICE_ACCOUNT_EMAIL
        or service_account.get("client_email", "")
    )
    private_key_pem = service_account.get("private_key", "")
    if not service_account_email or not private_key_pem:
        raise ImproperlyConfigured("Google Wallet service-account JSON is incomplete")

    signing_key = serialization.load_pem_private_key(
        private_key_pem.encode("utf-8"),
        password=None,
    )

    class_id = f"{issuer_id}.{class_suffix}"
    object_id = object_id or f"{issuer_id}.{customer_id}"

    loyalty_object = {
        "id": object_id,
        "classId": class_id,
        "accountId": customer_id,
        "accountName": name,
        "state": "active",
        "barcode": {
            "type": "qrCode",
            "value": customer_id,
            "alternateText": customer_id,
        },
    }
    if customer_image_url:
        loyalty_object["heroImage"] = {
            "sourceUri": {"uri": customer_image_url},
            "contentDescription": {
                "defaultValue": {
                    "language": "pl-PL",
                    "value": image_description,
                }
            },
        }

    claims = {
        "iss": service_account_email,
        "aud": "google",
        "typ": "savetowallet",
        "iat": int(time.time()),
        "origins": settings.GOOGLE_WALLET_ORIGINS,
        "payload": {"loyaltyObjects": [loyalty_object]},
    }
    encoded_jwt = jwt.encode(claims, signing_key, algorithm="RS256")
    return f"https://pay.google.com/gp/v/save/{encoded_jwt}"
