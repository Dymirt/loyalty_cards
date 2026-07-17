"""Consent-gated, idempotent Brevo contact synchronization."""

from __future__ import annotations

import time
from urllib.parse import quote

import requests
from django.conf import settings
from django.utils import timezone

from customers.models import ConsentRecord, CustomerExternalIdentity
from integrations.contracts import (
    IntegrationAuthenticationError,
    IntegrationConfigurationError,
    ProviderResult,
    RetryableIntegrationError,
    SystemCheckResult,
)
from integrations.models import IntegrationConnection


PROVIDER = "brevo"


class ConsentRequiredError(IntegrationConfigurationError):
    error_code = "marketing_consent_required"


def has_current_marketing_consent(customer):
    latest = (
        ConsentRecord.objects.filter(
            tenant=customer.tenant,
            customer=customer,
            purpose="marketing",
        )
        .order_by("-recorded_at", "-pk")
        .first()
    )
    return bool(latest and latest.granted and latest.revoked_at is None)


def get_connection(tenant):
    try:
        connection = IntegrationConnection.objects.get(
            tenant=tenant,
            provider=IntegrationConnection.Provider.BREVO,
            enabled=True,
        )
    except IntegrationConnection.DoesNotExist as exc:
        raise IntegrationConfigurationError("Brevo is not enabled.") from exc
    if not connection.configuration.get("list_id") or not connection.has_secret("api_key"):
        raise IntegrationConfigurationError("Brevo tenant configuration is incomplete.")
    return connection


def _retry_after(response, fallback=1):
    raw = response.headers.get("x-sib-ratelimit-reset", "")
    try:
        return max(1, min(int(raw), 3600))
    except (TypeError, ValueError):
        return fallback


class BrevoAdapter:
    def __init__(self, connection, *, session=requests, sleep=time.sleep):
        self.connection = connection
        self.session = session
        self.sleep = sleep
        if not connection.enabled:
            raise IntegrationConfigurationError("Brevo is not enabled.")
        self.api_key = connection.get_secret("api_key")
        self.list_id = connection.configuration.get("list_id")
        if not self.api_key or not self.list_id:
            raise IntegrationConfigurationError("Brevo configuration is incomplete.")

    @property
    def headers(self):
        return {"api-key": self.api_key, "content-type": "application/json"}

    def _request(self, method, path, **kwargs):
        url = f"{settings.BREVO_API_BASE_URL.rstrip('/')}/{path.lstrip('/')}"
        attempts = settings.INTEGRATION_HTTP_RETRIES + 1
        for attempt in range(attempts):
            try:
                response = getattr(self.session, method)(
                    url,
                    headers=self.headers,
                    timeout=settings.BREVO_HTTP_TIMEOUT,
                    **kwargs,
                )
            except (requests.Timeout, requests.ConnectionError) as exc:
                if attempt + 1 >= attempts:
                    raise RetryableIntegrationError(error_code="brevo_network") from exc
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
                        error_code=f"brevo_http_{status_code}",
                        retry_after=delay,
                    )
                self.sleep(delay)
                continue
            if response.status_code in (401, 403):
                raise IntegrationAuthenticationError(
                    "Brevo API key was rejected.", error_code="brevo_unauthorized"
                )
            return response
        raise RetryableIntegrationError(error_code="brevo_network")

    def _phone(self, customer):
        phone = customer.phone or ""
        if phone and not phone.startswith("+"):
            code = self.connection.configuration.get(
                "default_phone_country_code", "+48"
            )
            phone = f"{code}{phone}"
        return phone

    def _payload(self, customer):
        attributes = {
            "FNAME": customer.first_name or "",
            "LNAME": customer.last_name or "",
        }
        phone = self._phone(customer)
        if phone:
            attributes["SMS"] = phone
        payload = {
            "ext_id": f"tenant-{customer.tenant_id}-customer-{customer.pk}",
            "attributes": attributes,
            "listIds": [int(self.list_id)],
            "updateEnabled": True,
        }
        if customer.email:
            payload["email"] = customer.email
        return payload

    def _existing_contact(self, customer):
        identifier = customer.email or f"tenant-{customer.tenant_id}-customer-{customer.pk}"
        response = self._request("get", f"contacts/{quote(identifier, safe='')}")
        response.raise_for_status()
        return response.json()

    def upsert_contact(self, customer):
        if customer.tenant_id != self.connection.tenant_id:
            raise ValueError("Customer and Brevo connection must share a tenant.")
        identity, _ = CustomerExternalIdentity.objects.get_or_create(
            tenant=customer.tenant,
            customer=customer,
            provider=PROVIDER,
        )
        identity.last_attempted_at = timezone.now()
        identity.save(update_fields=("last_attempted_at", "updated_at"))
        if not has_current_marketing_consent(customer):
            identity.sync_status = CustomerExternalIdentity.SyncStatus.DISABLED
            identity.last_error_code = ConsentRequiredError.error_code
            identity.save(
                update_fields=(
                    "last_attempted_at",
                    "sync_status",
                    "last_error_code",
                    "updated_at",
                )
            )
            raise ConsentRequiredError()
        if not customer.email and not customer.phone:
            raise IntegrationConfigurationError(
                "Customer has no Brevo identifier.", error_code="contact_identifier_missing"
            )
        reconciled_remote_id = ""
        response = self._request("post", "contacts", json=self._payload(customer))
        if response.status_code == 400:
            error = response.json() if response.content else {}
            if error.get("code") in {"duplicate_parameter", "duplicate_request"}:
                existing = self._existing_contact(customer)
                reconciled_remote_id = str(existing.get("id") or "")
                current_lists = existing.get("listIds") or []
                update_payload = self._payload(customer)
                update_payload.pop("email", None)
                update_payload.pop("ext_id", None)
                update_payload.pop("updateEnabled", None)
                update_payload["listIds"] = sorted(
                    {int(value) for value in [*current_lists, int(self.list_id)]}
                )
                identifier = customer.email or self._payload(customer)["ext_id"]
                response = self._request(
                    "put",
                    f"contacts/{quote(identifier, safe='')}",
                    json=update_payload,
                )
        response.raise_for_status()
        body = response.json() if response.content else {}
        remote_id = str(
            body.get("id") or reconciled_remote_id or identity.remote_id or ""
        )
        identity.remote_id = remote_id or None
        identity.sync_status = CustomerExternalIdentity.SyncStatus.SYNCED
        identity.last_synced_at = timezone.now()
        identity.last_error_code = ""
        identity.full_clean()
        identity.save()
        return ProviderResult(remote_id=remote_id)

    def test_connection(self):
        response = self._request("get", "account")
        response.raise_for_status()
        return ProviderResult(metadata={"account": "available"})


def adapter_for_tenant(tenant, *, session=requests, sleep=time.sleep):
    return BrevoAdapter(get_connection(tenant), session=session, sleep=sleep)


def test_connection(connection):
    result = BrevoAdapter(connection).test_connection()
    now = timezone.now()
    connection.last_tested_at = now
    connection.last_success_at = now
    connection.last_error_code = ""
    connection.save(
        update_fields=("last_tested_at", "last_success_at", "last_error_code", "updated_at")
    )
    return result


def system_connection_check():
    connections = list(
        IntegrationConnection.objects.select_related("tenant")
        .filter(provider=IntegrationConnection.Provider.BREVO, enabled=True)
        .order_by("tenant__name", "pk")
    )
    if not connections:
        return SystemCheckResult(
            ok=False,
            summary="Brak aktywnych połączeń Brevo firm.",
        )
    details = []
    failures = 0
    for connection in connections:
        try:
            test_connection(connection)
        except Exception as exc:
            failures += 1
            code = getattr(exc, "error_code", type(exc).__name__)
            details.append(f"{connection.tenant.name}: błąd ({code})")
        else:
            details.append(f"{connection.tenant.name}: OK")
    return SystemCheckResult(
        ok=failures == 0,
        summary=(
            f"Sprawdzono {len(connections)} aktywnych połączeń; błędy: {failures}."
        ),
        details=tuple(details),
    )


__all__ = [
    "BrevoAdapter",
    "ConsentRequiredError",
    "adapter_for_tenant",
    "get_connection",
    "has_current_marketing_consent",
    "system_connection_check",
    "test_connection",
]
