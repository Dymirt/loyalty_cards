"""Dotykačka Connector v2 and tenant-scoped customer adapter."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from datetime import timedelta
from urllib.parse import quote

import requests
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import transaction
from django.utils import timezone

from customers.models import CustomerExternalIdentity
from integrations.contracts import (
    IntegrationAuthenticationError,
    IntegrationConfigurationError,
    ProviderResult,
    RetryableIntegrationError,
    SystemCheckResult,
)
from integrations.models import IntegrationConnection
from tenants.authorization import can_manage_integrations

from .models import DotykackaAccessToken, DotykackaConnectState


PROVIDER = "dotykacka"
CONNECTOR_SETTING_NAMES = (
    "DOTYKACKA_CONNECTOR_CLIENT_ID",
    "DOTYKACKA_CONNECTOR_CLIENT_SECRET",
)


def _user_authorization_header(value):
    value = str(value).strip()
    if not value:
        return ""
    return value if value.startswith("User ") else f"User {value}"


def get_connection(tenant, *, require_enabled=True):
    try:
        connection = IntegrationConnection.objects.get(
            tenant=tenant,
            provider=IntegrationConnection.Provider.DOTYKACKA,
        )
    except IntegrationConnection.DoesNotExist as exc:
        raise IntegrationConfigurationError("Dotykačka is not configured.") from exc
    if require_enabled and not connection.enabled:
        raise IntegrationConfigurationError("Dotykačka is not enabled.")
    config = connection.configuration
    if not config.get("cloud_id") or not config.get("discount_group_id"):
        raise IntegrationConfigurationError("Dotykačka tenant configuration is incomplete.")
    if not connection.has_secret("refresh_token"):
        raise IntegrationConfigurationError("Dotykačka Refresh Token is missing.")
    return connection


def missing_connector_settings():
    return tuple(
        name for name in CONNECTOR_SETTING_NAMES if not str(getattr(settings, name, "")).strip()
    )


def connector_payload(*, redirect_uri, timestamp=None, state=None):
    missing = missing_connector_settings()
    if missing:
        if len(missing) == len(CONNECTOR_SETTING_NAMES):
            error_code = "dotykacka_connector_credentials_missing"
        elif missing[0] == "DOTYKACKA_CONNECTOR_CLIENT_ID":
            error_code = "dotykacka_connector_client_id_missing"
        else:
            error_code = "dotykacka_connector_client_secret_missing"
        raise IntegrationConfigurationError(
            "Dotykačka platform Connector credentials are not configured.",
            error_code=error_code,
        )
    client_id = str(settings.DOTYKACKA_CONNECTOR_CLIENT_ID).strip()
    client_secret = str(settings.DOTYKACKA_CONNECTOR_CLIENT_SECRET).strip()
    timestamp = int(timestamp if timestamp is not None else time.time())
    state = state or secrets.token_urlsafe(32)
    signature = hmac.new(
        client_secret.encode("utf-8"),
        str(timestamp).encode("ascii"),
        hashlib.sha256,
    ).hexdigest()
    return {
        "client_id": client_id,
        "timestamp": timestamp,
        "signature": signature,
        "scope": "*",
        "redirect_uri": redirect_uri,
        "state": state,
    }


def _digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def begin_connection(*, tenant, user, session_key, redirect_uri):
    if not session_key:
        raise ValueError("A persisted browser session is required.")
    connection, _ = IntegrationConnection.objects.get_or_create(
        tenant=tenant,
        provider=IntegrationConnection.Provider.DOTYKACKA,
    )
    payload = connector_payload(redirect_uri=redirect_uri)
    state = DotykackaConnectState(
        tenant=tenant,
        connection=connection,
        created_by=user,
        state_digest=_digest(payload["state"]),
        session_digest=_digest(session_key),
        redirect_uri=redirect_uri,
        expires_at=timezone.now() + timedelta(minutes=15),
    )
    state.full_clean()
    state.save()
    return settings.DOTYKACKA_CONNECTOR_URL, payload


@transaction.atomic
def complete_connection(*, state, refresh_token, cloud_id, user, session_key):
    if not state or not refresh_token or not cloud_id or not session_key:
        raise IntegrationAuthenticationError(
            "Dotykačka callback is incomplete.", error_code="callback_incomplete"
        )
    try:
        pending = (
            DotykackaConnectState.objects.select_for_update()
            .select_related("connection")
            .get(state_digest=_digest(state))
        )
    except DotykackaConnectState.DoesNotExist as exc:
        raise IntegrationAuthenticationError(
            "Dotykačka callback state is invalid.", error_code="state_invalid"
        ) from exc
    now = timezone.now()
    if (
        pending.used_at
        or pending.expires_at <= now
        or pending.created_by_id != user.pk
        or not can_manage_integrations(user, pending.tenant)
        or not hmac.compare_digest(pending.session_digest, _digest(session_key))
    ):
        raise IntegrationAuthenticationError(
            "Dotykačka callback state expired or was already used.",
            error_code="state_rejected",
        )
    connection = pending.connection
    credentials = connection.get_credentials()
    configuration = dict(connection.configuration)
    current_cloud_id = str(configuration.get("cloud_id") or "")
    if current_cloud_id and current_cloud_id != str(cloud_id):
        raise IntegrationAuthenticationError(
            "Disconnect the current Dotykačka cloud before selecting another one.",
            error_code="cloud_change_requires_disconnect",
        )
    credentials["refresh_token"] = refresh_token
    configuration["cloud_id"] = str(cloud_id)
    connection.configuration = configuration
    connection.set_credentials(credentials)
    connection.last_error_code = ""
    connection.save(
        update_fields=(
            "configuration",
            "credentials_encrypted",
            "last_error_code",
            "updated_at",
        )
    )
    pending.used_at = now
    pending.save(update_fields=("used_at",))
    return connection


@transaction.atomic
def disconnect_connection(*, tenant):
    try:
        connection = IntegrationConnection.objects.select_for_update().get(
            tenant=tenant,
            provider=IntegrationConnection.Provider.DOTYKACKA,
        )
    except IntegrationConnection.DoesNotExist as exc:
        raise IntegrationConfigurationError(
            "Dotykačka is not configured."
        ) from exc
    now = timezone.now()
    credentials = connection.get_credentials()
    credentials.pop("refresh_token", None)
    configuration = dict(connection.configuration)
    previous_cloud_id = str(configuration.pop("cloud_id", "") or "")
    connection.configuration = configuration
    connection.set_credentials(credentials)
    connection.enabled = False
    connection.last_error_code = ""
    connection.save(
        update_fields=(
            "configuration",
            "credentials_encrypted",
            "enabled",
            "last_error_code",
            "updated_at",
        )
    )
    DotykackaAccessToken.objects.filter(
        connection=connection,
        invalidated_at__isnull=True,
    ).update(invalidated_at=now)
    DotykackaConnectState.objects.filter(
        connection=connection,
        used_at__isnull=True,
    ).update(used_at=now)
    return connection, previous_cloud_id


def _retry_after(response, fallback=1):
    raw = response.headers.get("Retry-After", "") if response is not None else ""
    try:
        return max(1, min(int(raw), 3600))
    except (TypeError, ValueError):
        return fallback


class DotykackaAdapter:
    def __init__(self, connection, *, session=requests, sleep=time.sleep):
        self.connection = connection
        self.session = session
        self.sleep = sleep
        if not connection.enabled:
            raise IntegrationConfigurationError("Dotykačka is not enabled.")
        self.cloud_id = connection.configuration.get("cloud_id") or ""
        self.discount_group_id = connection.configuration.get("discount_group_id") or ""
        if not self.cloud_id or not self.discount_group_id:
            raise IntegrationConfigurationError("Dotykačka configuration is incomplete.")
        if not connection.has_secret("refresh_token"):
            raise IntegrationConfigurationError(
                "Dotykačka tenant Refresh Token is missing.",
                error_code="dotykacka_refresh_token_missing",
            )

    @property
    def api_base_url(self):
        return settings.DOTYKACKA_API_BASE_URL.rstrip("/")

    def _refresh_header(self):
        refresh_token = self.connection.get_secret("refresh_token")
        return _user_authorization_header(refresh_token)

    @property
    def authorization_source(self):
        return "tenant_refresh_token"

    def _request(self, method, url, *, retry=True, **kwargs):
        attempts = settings.INTEGRATION_HTTP_RETRIES + 1 if retry else 1
        last_exc = None
        for attempt in range(attempts):
            try:
                response = getattr(self.session, method)(
                    url,
                    timeout=settings.DOTYKACKA_HTTP_TIMEOUT,
                    **kwargs,
                )
            except (requests.Timeout, requests.ConnectionError) as exc:
                last_exc = exc
                if attempt + 1 >= attempts:
                    raise RetryableIntegrationError(
                        error_code="dotykacka_network"
                    ) from exc
                self.sleep(min(2 ** attempt, 5))
                continue
            status_code = (
                response.status_code
                if isinstance(response.status_code, int)
                else 200
            )
            if status_code == 429 or 500 <= status_code < 600:
                delay = _retry_after(response, min(2 ** attempt, 5))
                if attempt + 1 >= attempts:
                    raise RetryableIntegrationError(
                        error_code=f"dotykacka_http_{status_code}",
                        retry_after=delay,
                    )
                self.sleep(delay)
                continue
            return response
        raise RetryableIntegrationError(error_code="dotykacka_network") from last_exc

    def fetch_access_token(self, *, legacy_cache=False):
        response = self._request(
            "post",
            f"{self.api_base_url}/v2/signin/token",
            json={"_cloudId": self.cloud_id},
            headers={
                "Authorization": self._refresh_header(),
                "Content-Type": "application/json",
            },
        )
        if response.status_code == 401:
            raise IntegrationAuthenticationError(
                "Dotykačka authorization was rejected during access-token exchange.",
                error_code="dotykacka_refresh_rejected",
            )
        response.raise_for_status()
        token = response.json().get("accessToken")
        if not token:
            raise RetryableIntegrationError(error_code="dotykacka_token_missing")
        now = timezone.now()
        cached = DotykackaAccessToken(
            tenant=self.connection.tenant,
            connection=self.connection,
            cloud_id=str(self.cloud_id),
            obtained_at=now,
            expires_at=now + timedelta(hours=1),
        )
        cached.set_token(token)
        cached.full_clean()
        cached.save()
        if legacy_cache:
            from dotykacka.models import AccessToken

            AccessToken.objects.create(connection=self.connection, token=token)
        return token

    @transaction.atomic
    def valid_access_token(self, *, force_refresh=False, legacy_cache=False):
        # Lock the connection row so concurrent web/worker requests cannot
        # refresh the same cloud token in parallel.
        self.connection = IntegrationConnection.objects.select_for_update().get(
            pk=self.connection.pk
        )
        if not force_refresh:
            skew = timedelta(seconds=settings.DOTYKACKA_TOKEN_EXPIRY_SKEW)
            cached = (
                DotykackaAccessToken.objects.filter(
                    tenant=self.connection.tenant,
                    connection=self.connection,
                    cloud_id=str(self.cloud_id),
                    invalidated_at__isnull=True,
                    expires_at__gt=timezone.now() + skew,
                )
                .order_by("-obtained_at", "-pk")
                .first()
            )
            if cached:
                return cached.get_token()
            if legacy_cache:
                legacy = self.connection.access_tokens.order_by("created_at", "pk").last()
                if legacy and legacy.created_at + timedelta(hours=1) > timezone.now():
                    return legacy.token
        return self.fetch_access_token(legacy_cache=legacy_cache)

    def _authorized(self, method, url, **kwargs):
        token = self.valid_access_token()
        headers = dict(kwargs.pop("headers", {}))
        headers["Authorization"] = f"Bearer {token}"
        response = self._request(method, url, headers=headers, **kwargs)
        if response.status_code != 401:
            return response
        DotykackaAccessToken.objects.filter(
            connection=self.connection,
            cloud_id=str(self.cloud_id),
            invalidated_at__isnull=True,
        ).update(invalidated_at=timezone.now())
        token = self.valid_access_token(force_refresh=True)
        headers["Authorization"] = f"Bearer {token}"
        response = self._request(method, url, headers=headers, retry=False, **kwargs)
        if response.status_code == 401:
            raise IntegrationAuthenticationError(
                "Dotykačka access was rejected.", error_code="dotykacka_unauthorized"
            )
        return response

    def _customers_url(self):
        return f"{self.api_base_url}/v2/clouds/{quote(str(self.cloud_id))}/customers"

    def list_customers(self, *, legacy_cache=False, access_token=""):
        customers = []
        page = 1
        legacy_token = access_token or (
            self.valid_access_token(legacy_cache=True) if legacy_cache else ""
        )
        while page <= settings.DOTYKACKA_MAX_PAGES:
            if legacy_cache:
                response = self.session.get(
                    self._customers_url(),
                    headers={"Authorization": f"Bearer {legacy_token}"},
                    params={"page": page},
                    timeout=settings.DOTYKACKA_HTTP_TIMEOUT,
                )
            else:
                response = self._authorized(
                    "get", self._customers_url(), params={"page": page}
                )
            response.raise_for_status()
            payload = response.json()
            customers.extend(payload.get("data", []))
            last_page = int(payload.get("lastPage") or page)
            if page >= last_page:
                break
            page += 1
        else:
            raise RetryableIntegrationError(error_code="dotykacka_pagination_limit")
        return [
            item
            for item in customers
            if str(item.get("_discountGroupId")) == str(self.discount_group_id)
        ]

    def _legacy_upsert(self, customer, *, access_token):
        """Exact historical request shape used only by the compatibility module."""

        payload = self._customer_payload(customer)
        payload["points"] = 0.0
        response = self.session.post(
            self._customers_url(),
            json=[payload],
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            timeout=settings.DOTYKACKA_HTTP_TIMEOUT,
        )
        response.raise_for_status()
        return response.json() if response.content else None

    def _customer_payload(self, customer):
        return {
            "_cloudId": self.cloud_id,
            "addressLine1": "",
            "barcode": customer.klient_id,
            "companyId": "",
            "companyName": "",
            "deleted": False,
            "display": True,
            "email": customer.email or "",
            "firstName": customer.first_name or "",
            "headerPrint": "",
            "hexColor": "#F32C24",
            "internalNote": "",
            "lastName": customer.last_name or "",
            "phone": customer.phone or "",
            "tags": [],
            "vatId": "",
            "zip": "",
            "flags": "0",
            "_discountGroupId": self.discount_group_id,
        }

    def upsert_customer(self, customer):
        if customer.tenant_id != self.connection.tenant_id:
            raise ValueError("Customer and Dotykačka connection must share a tenant.")
        identity, _ = CustomerExternalIdentity.objects.get_or_create(
            tenant=customer.tenant,
            customer=customer,
            provider=PROVIDER,
        )
        identity.last_attempted_at = timezone.now()
        identity.save(update_fields=("last_attempted_at", "updated_at"))
        response = self._authorized(
            "post",
            self._customers_url(),
            json=[self._customer_payload(customer)],
            headers={"Content-Type": "application/json"},
        )
        if response.status_code in (409, 422):
            match = next(
                (
                    item
                    for item in self.list_customers()
                    if item.get("barcode") == customer.klient_id
                ),
                None,
            )
            if match is None:
                response.raise_for_status()
            payload = match
        else:
            response.raise_for_status()
            body = response.json() if response.content else {}
            if isinstance(body, list):
                payload = body[0] if body else {}
            elif isinstance(body.get("data"), list):
                payload = body["data"][0] if body["data"] else {}
            else:
                payload = body
        remote_id = str(payload.get("id") or payload.get("_id") or identity.remote_id or "")
        identity.remote_id = remote_id or None
        identity.sync_status = CustomerExternalIdentity.SyncStatus.SYNCED
        identity.last_synced_at = timezone.now()
        identity.last_error_code = ""
        identity.full_clean()
        identity.save()
        return ProviderResult(remote_id=remote_id)

    def test_connection(self):
        self.valid_access_token(force_refresh=True)
        return ProviderResult(
            metadata={
                "cloud_id": self.cloud_id,
                "authorization_source": self.authorization_source,
            }
        )


def adapter_for_tenant(tenant, *, session=requests, sleep=time.sleep):
    return DotykackaAdapter(get_connection(tenant), session=session, sleep=sleep)


def test_connection(connection):
    result = DotykackaAdapter(connection).test_connection()
    now = timezone.now()
    connection.last_tested_at = now
    connection.last_success_at = now
    connection.last_error_code = ""
    connection.save(
        update_fields=("last_tested_at", "last_success_at", "last_error_code", "updated_at")
    )
    return result


def connector_system_check():
    missing = missing_connector_settings()
    if missing:
        return SystemCheckResult(
            ok=False,
            summary="Brakuje poświadczeń platformowej aplikacji Dotykačka Connector.",
            details=tuple(f"Brak zmiennej: {name}" for name in missing),
        )
    payload = connector_payload(
        redirect_uri=f"{settings.APP_BASE_URL}/integrations/dotykacka/callback"
    )
    if len(payload["signature"]) != 64:
        return SystemCheckResult(
            ok=False,
            summary="Nie udało się przygotować podpisu Connector.",
        )
    return SystemCheckResult(
        ok=True,
        summary="Poświadczenia platformy generują podpis Connector HMAC-SHA256.",
        details=(
            "Client ID: skonfigurowany.",
            "Client Secret: skonfigurowany.",
            "Poprawność poświadczeń po stronie Dotykačka jest potwierdzana podczas interaktywnego podłączania firmy.",
        ),
    )


def tenant_connections_system_check():
    connections = list(
        IntegrationConnection.objects.select_related("tenant")
        .filter(provider=IntegrationConnection.Provider.DOTYKACKA, enabled=True)
        .order_by("tenant__name", "pk")
    )
    if not connections:
        return SystemCheckResult(
            ok=False,
            summary="Brak aktywnych połączeń Dotykačka firm.",
        )
    details = []
    failures = 0
    for connection in connections:
        try:
            test_connection(connection)
        except Exception as exc:
            failures += 1
            now = timezone.now()
            connection.last_tested_at = now
            connection.last_error_code = getattr(
                exc, "error_code", type(exc).__name__
            )[:80]
            connection.save(
                update_fields=("last_tested_at", "last_error_code", "updated_at")
            )
            details.append(
                f"{connection.tenant.name}: błąd ({connection.last_error_code})"
            )
        else:
            details.append(
                f"{connection.tenant.name}: OK · Refresh Token firmy (zaszyfrowany) · Cloud ID {connection.configuration.get('cloud_id')}"
            )
    return SystemCheckResult(
        ok=failures == 0,
        summary=(
            f"Sprawdzono {len(connections)} aktywnych połączeń; błędy: {failures}."
        ),
        details=tuple(details),
    )


__all__ = [
    "DotykackaAdapter",
    "adapter_for_tenant",
    "begin_connection",
    "complete_connection",
    "connector_system_check",
    "connector_payload",
    "disconnect_connection",
    "get_connection",
    "missing_connector_settings",
    "tenant_connections_system_check",
    "test_connection",
]
