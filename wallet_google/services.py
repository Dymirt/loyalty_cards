"""Google Wallet loyalty-object mapping and signed save-link issuance."""

import json
import re
import time
from pathlib import Path
from urllib.parse import quote

import jwt
import requests
from cryptography.hazmat.primitives import serialization
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from cards.codes import card_number
from integrations.contracts import (
    IntegrationAuthenticationError,
    ProviderResult,
    RetryableIntegrationError,
    SystemCheckResult,
)
from integrations.models import IntegrationConnection
from wallets.services import wallet_identity


def platform_issuer_id() -> str:
    issuer_id = str(settings.GOOGLE_WALLET_ISSUER_ID).strip()
    if not issuer_id or not issuer_id.isdigit():
        raise ImproperlyConfigured(
            "Google Wallet platform issuer ID is not configured."
        )
    return issuer_id


def tenant_class_suffix(tenant) -> str:
    """Use the tenant's unique card prefix as its stable Google class identity."""

    suffix = re.sub(r"[^A-Za-z0-9._-]", "_", tenant.card_prefix or "")
    if not suffix:
        raise ImproperlyConfigured("The tenant has no Google Wallet class identity.")
    return suffix


def get_wallet_url(
    name: str,
    customer_id: str,
    *,
    issuer_id: str,
    class_suffix: str,
    object_id: str = "",
    customer_image_url: str = "",
    image_description: str = "Karta lojalnościowa",
    _jwt=jwt,
    _serialization=serialization,
) -> str:
    keyfile = Path(settings.GOOGLE_WALLET_SERVICE_ACCOUNT_FILE)
    if not keyfile.is_file():
        raise ImproperlyConfigured(
            f"Google Wallet service-account file not found: {keyfile}"
        )
    if not issuer_id or not class_suffix:
        raise ImproperlyConfigured("Google Wallet platform/class configuration is incomplete")
    service_account = json.loads(keyfile.read_text(encoding="utf-8"))
    service_account_email = (
        settings.GOOGLE_WALLET_SERVICE_ACCOUNT_EMAIL
        or service_account.get("client_email", "")
    )
    private_key_pem = service_account.get("private_key", "")
    if not service_account_email or not private_key_pem:
        raise ImproperlyConfigured("Google Wallet service-account JSON is incomplete")
    signing_key = _serialization.load_pem_private_key(
        private_key_pem.encode("utf-8"), password=None
    )
    class_id = f"{issuer_id}.{class_suffix}"
    object_id = object_id or f"{issuer_id}.{customer_id}"
    loyalty_object = {
        "id": object_id,
        "classId": class_id,
        "accountId": customer_id,
        "accountName": name,
        "state": "ACTIVE",
        "barcode": {
            "type": "QR_CODE",
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
    encoded_jwt = _jwt.encode(claims, signing_key, algorithm="RS256")
    return f"https://pay.google.com/gp/v/save/{encoded_jwt}"


def _service_account():
    keyfile = Path(settings.GOOGLE_WALLET_SERVICE_ACCOUNT_FILE)
    if not keyfile.is_file():
        raise ImproperlyConfigured(
            f"Google Wallet service-account file not found: {keyfile}"
        )
    payload = json.loads(keyfile.read_text(encoding="utf-8"))
    if not payload.get("client_email") or not payload.get("private_key"):
        raise ImproperlyConfigured("Google Wallet service-account JSON is incomplete")
    return payload


class GoogleWalletRestClient:
    """Small REST adapter using the existing service-account key and requests."""

    scope = "https://www.googleapis.com/auth/wallet_object.issuer"

    def __init__(self, *, session=requests, sleep=time.sleep):
        self.session = session
        self.sleep = sleep
        self._token = ""

    def _access_token(self, *, force=False):
        if self._token and not force:
            return self._token
        account = _service_account()
        now = int(time.time())
        assertion = jwt.encode(
            {
                "iss": account["client_email"],
                "scope": self.scope,
                "aud": account.get("token_uri", "https://oauth2.googleapis.com/token"),
                "iat": now,
                "exp": now + 3600,
            },
            account["private_key"],
            algorithm="RS256",
        )
        try:
            response = self.session.post(
                account.get("token_uri", "https://oauth2.googleapis.com/token"),
                data={
                    "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                    "assertion": assertion,
                },
                timeout=settings.GOOGLE_WALLET_HTTP_TIMEOUT,
            )
        except (requests.Timeout, requests.ConnectionError) as exc:
            raise RetryableIntegrationError(
                error_code="google_wallet_token_network"
            ) from exc
        if response.status_code == 429 or response.status_code >= 500:
            raise RetryableIntegrationError(
                error_code=f"google_wallet_token_http_{response.status_code}"
            )
        if response.status_code in (401, 403):
            raise IntegrationAuthenticationError(
                error_code="google_wallet_service_account_rejected"
            )
        response.raise_for_status()
        self._token = response.json().get("access_token", "")
        if not self._token:
            raise RetryableIntegrationError(error_code="google_wallet_token_missing")
        return self._token

    def _request(self, method, path, *, retry_401=True, **kwargs):
        url = f"{settings.GOOGLE_WALLET_API_BASE_URL.rstrip('/')}/{path.lstrip('/')}"
        attempts = settings.INTEGRATION_HTTP_RETRIES + 1
        for attempt in range(attempts):
            headers = dict(kwargs.pop("headers", {}))
            headers["Authorization"] = f"Bearer {self._access_token()}"
            headers.setdefault("Content-Type", "application/json")
            try:
                response = getattr(self.session, method)(
                    url,
                    headers=headers,
                    timeout=settings.GOOGLE_WALLET_HTTP_TIMEOUT,
                    **kwargs,
                )
            except (requests.Timeout, requests.ConnectionError) as exc:
                if attempt + 1 >= attempts:
                    raise RetryableIntegrationError(
                        error_code="google_wallet_network"
                    ) from exc
                self.sleep(min(2 ** attempt, 5))
                continue
            if response.status_code == 401 and retry_401:
                self._access_token(force=True)
                return self._request(method, path, retry_401=False, **kwargs)
            if response.status_code == 429 or 500 <= response.status_code < 600:
                retry_after = response.headers.get("Retry-After", "")
                try:
                    delay = max(1, min(int(retry_after), 3600))
                except (TypeError, ValueError):
                    delay = min(2 ** attempt, 5)
                if attempt + 1 >= attempts:
                    raise RetryableIntegrationError(
                        error_code=f"google_wallet_http_{response.status_code}",
                        retry_after=delay,
                    )
                self.sleep(delay)
                continue
            return response
        raise RetryableIntegrationError(error_code="google_wallet_network")

    def _upsert(self, resource, resource_id, payload):
        encoded_id = quote(resource_id, safe="")
        existing = self._request("get", f"{resource}/{encoded_id}")
        if existing.status_code == 404:
            created = self._request("post", resource, json=payload)
            if created.status_code == 409:
                return self._request("get", f"{resource}/{encoded_id}")
            created.raise_for_status()
            return created
        existing.raise_for_status()
        patched = self._request(
            "patch", f"{resource}/{encoded_id}", json=payload
        )
        patched.raise_for_status()
        return patched

    def upsert_loyalty(self, *, class_payload, object_payload):
        self._upsert("loyaltyClass", class_payload["id"], class_payload)
        self._upsert("loyaltyObject", object_payload["id"], object_payload)
        return ProviderResult(remote_id=object_payload["id"])

    def test_issuer(self, issuer_id):
        """Authenticate and perform a read-only issuer-scoped API request."""

        response = self._request(
            "get",
            "loyaltyClass",
            params={"issuerId": issuer_id, "maxResults": 1},
        )
        if response.status_code in (401, 403):
            raise IntegrationAuthenticationError(
                error_code="google_wallet_issuer_access_rejected"
            )
        response.raise_for_status()
        return ProviderResult(metadata={"issuer_id": issuer_id})


class GoogleWalletIssuer:
    provider = "google"

    def issue(
        self,
        customer,
        *,
        url_builder=None,
        remote_sync=None,
        rest_client=None,
    ):
        try:
            connection = IntegrationConnection.objects.get(
                tenant=customer.tenant,
                provider=IntegrationConnection.Provider.GOOGLE_WALLET,
                enabled=True,
            )
        except IntegrationConnection.DoesNotExist as exc:
            raise ImproperlyConfigured(
                "Google Wallet is not enabled for this tenant."
            ) from exc
        issuer_id = platform_issuer_id()
        class_suffix = tenant_class_suffix(customer.tenant)
        wallet = wallet_identity(customer)
        expected_object_id = (
            f"{issuer_id}.{re.sub(r'[^A-Za-z0-9._-]', '_', customer.klient_id)}"
        )
        if wallet.google_object_id and wallet.google_object_id != expected_object_id:
            raise ImproperlyConfigured(
                "The stored Google Wallet object belongs to a different platform issuer."
            )
        if not wallet.google_object_id:
            wallet.google_object_id = expected_object_id
        number = card_number(customer.klient_id)
        customer_name = " ".join(
            part for part in (customer.first_name, customer.last_name) if part
        )
        loyalty_object = {
            "id": wallet.google_object_id,
            "classId": f"{issuer_id}.{class_suffix}",
            "accountId": customer.klient_id,
            "accountName": customer_name,
            "state": "ACTIVE",
            "barcode": {
                "type": "QR_CODE",
                "value": customer.klient_id,
                "alternateText": customer.klient_id,
            },
        }
        if remote_sync is None:
            remote_sync = settings.GOOGLE_WALLET_REMOTE_SYNC_ENABLED
        if remote_sync:
            public_name = customer.tenant.brand.public_name or customer.tenant.name
            logo_path = customer.tenant.brand.logo_path or "logo_atelier_cafe.png"
            class_payload = {
                "id": f"{issuer_id}.{class_suffix}",
                "issuerName": public_name,
                "programName": public_name,
                "reviewStatus": "UNDER_REVIEW",
                "programLogo": {
                    "sourceUri": {
                        "uri": f"{settings.APP_BASE_URL}/media/{logo_path}"
                    },
                    "contentDescription": {
                        "defaultValue": {
                            "language": "pl-PL",
                            "value": public_name,
                        }
                    },
                },
            }
            (rest_client or GoogleWalletRestClient()).upsert_loyalty(
                class_payload=class_payload,
                object_payload=loyalty_object,
            )
        builder = url_builder or get_wallet_url
        wallet_url = builder(
            name=customer_name,
            customer_id=customer.klient_id,
            issuer_id=issuer_id,
            class_suffix=class_suffix,
            object_id=wallet.google_object_id,
            customer_image_url=(
                f"{settings.APP_BASE_URL}/media/cropped_images/cropped_image_{number}.jpg"
            ),
            image_description=f"Karta lojalnościowa {customer.tenant.brand.public_name}",
        )
        wallet.google_save_url = wallet_url
        wallet.save(
            update_fields=("google_object_id", "google_save_url", "updated_at")
        )
        customer.google_jwt_url = wallet_url
        customer.save(update_fields=("google_jwt_url",))
        return wallet_url

    def test_connection(self, connection=None, *, rest_client=None):
        return (rest_client or GoogleWalletRestClient()).test_issuer(
            platform_issuer_id()
        )


issuer = GoogleWalletIssuer()


def test_connection(connection=None, *, rest_client=None):
    return issuer.test_connection(connection, rest_client=rest_client)


def system_connection_check():
    issuer_id = platform_issuer_id()
    test_connection()
    return SystemCheckResult(
        ok=True,
        summary="Uwierzytelnienie i odczyt API Google Wallet działają.",
        details=(f"Centralny ID wydawcy: {issuer_id}",),
    )


__all__ = [
    "GoogleWalletIssuer",
    "GoogleWalletRestClient",
    "get_wallet_url",
    "issuer",
    "platform_issuer_id",
    "system_connection_check",
    "tenant_class_suffix",
    "test_connection",
]
