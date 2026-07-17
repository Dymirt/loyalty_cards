"""Tenant-scoped Dotykačka API adapter."""

import requests
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils import timezone

from .models import AccessToken, IntegrationConnection, Tenant


def get_dotykacka_connection(tenant: Tenant) -> IntegrationConnection:
    try:
        connection = IntegrationConnection.objects.get(
            tenant=tenant,
            provider=IntegrationConnection.Provider.DOTYKACKA,
            enabled=True,
        )
    except IntegrationConnection.DoesNotExist as exc:
        raise ImproperlyConfigured(
            "Dotykačka is not enabled for this tenant."
        ) from exc

    config = connection.configuration
    if not config.get("cloud_id") or not config.get("discount_group_id"):
        raise ImproperlyConfigured("Dotykačka tenant configuration is incomplete.")
    if not connection.has_secret("authorization_token"):
        raise ImproperlyConfigured("Dotykačka authorization token is not configured.")
    return connection


def get_access_token(connection: IntegrationConnection) -> str:
    cloud_id = connection.configuration["cloud_id"]
    response = requests.post(
        "https://api.dotykacka.cz/v2/signin/token",
        json={"_cloudId": cloud_id},
        headers={
            "Authorization": connection.get_secret("authorization_token"),
            "Content-Type": "application/json",
        },
        timeout=settings.DOTYKACKA_HTTP_TIMEOUT,
    )
    response.raise_for_status()
    token = response.json().get("accessToken")
    if not token:
        raise RuntimeError("Dotykačka did not return an access token")

    AccessToken.objects.create(connection=connection, token=token)
    return token


def get_valid_access_token(connection: IntegrationConnection) -> str:
    access_token = connection.access_tokens.order_by("created_at", "pk").last()
    if (
        access_token
        and access_token.created_at + timezone.timedelta(hours=1) > timezone.now()
    ):
        return access_token.token
    return get_access_token(connection)


def register_dotykacka_customer(
    tenant: Tenant,
    barcode,
    first_name,
    last_name,
    email,
    phone,
):
    connection = get_dotykacka_connection(tenant)
    access_token = get_valid_access_token(connection)
    cloud_id = connection.configuration["cloud_id"]
    discount_group_id = connection.configuration["discount_group_id"]
    url = f"https://api.dotykacka.cz/v2/clouds/{cloud_id}/customers"
    body = [
        {
            "_cloudId": cloud_id,
            "addressLine1": "",
            "barcode": barcode,
            "companyId": "",
            "companyName": "",
            "deleted": False,
            "display": True,
            "email": email,
            "firstName": first_name,
            "headerPrint": "",
            "hexColor": "#F32C24",
            "internalNote": "",
            "lastName": last_name,
            "phone": phone,
            "points": 0.0,
            "tags": [],
            "vatId": "",
            "zip": "",
            "flags": "0",
            "_discountGroupId": discount_group_id,
        }
    ]
    response = requests.post(
        url,
        json=body,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        timeout=settings.DOTYKACKA_HTTP_TIMEOUT,
    )
    response.raise_for_status()
    return response.json() if response.content else None


def get_all_customers(tenant: Tenant):
    connection = get_dotykacka_connection(tenant)
    access_token = get_valid_access_token(connection)
    cloud_id = connection.configuration["cloud_id"]
    discount_group_id = connection.configuration["discount_group_id"]
    url = f"https://api.dotykacka.cz/v2/clouds/{cloud_id}/customers"
    headers = {"Authorization": f"Bearer {access_token}"}
    customers = []
    page = 1

    while True:
        response = requests.get(
            url,
            headers=headers,
            params={"page": page},
            timeout=settings.DOTYKACKA_HTTP_TIMEOUT,
        )
        response.raise_for_status()
        payload = response.json()
        customers.extend(payload.get("data", []))

        if str(page) == str(payload.get("lastPage", page)):
            break
        page += 1

    return [
        customer
        for customer in customers
        if str(customer.get("_discountGroupId")) == str(discount_group_id)
    ]
