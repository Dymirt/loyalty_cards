import requests
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils import timezone

from .models import AccessToken


def _validate_configuration():
    if not settings.DOTYKACKA_AUTHORIZATION_TOKEN:
        raise ImproperlyConfigured("DOTYKACKA_AUTHORIZATION_TOKEN is not configured")
    if not settings.DOTYKACKA_CLOUD_ID:
        raise ImproperlyConfigured("DOTYKACKA_CLOUD_ID is not configured")


def get_access_token():
    _validate_configuration()
    response = requests.post(
        "https://api.dotykacka.cz/v2/signin/token",
        json={"_cloudId": settings.DOTYKACKA_CLOUD_ID},
        headers={
            "Authorization": settings.DOTYKACKA_AUTHORIZATION_TOKEN,
            "Content-Type": "application/json",
        },
        timeout=settings.DOTYKACKA_HTTP_TIMEOUT,
    )
    response.raise_for_status()
    token = response.json().get("accessToken")
    if not token:
        raise RuntimeError("Dotykačka did not return an access token")

    AccessToken.objects.create(token=token)
    return token


def get_valid_access_token():
    access_token = AccessToken.objects.last()
    if (
        access_token
        and access_token.created_at + timezone.timedelta(hours=1) > timezone.now()
    ):
        return access_token.token
    return get_access_token()


def register_dotykacka_customer(barcode, first_name, last_name, email, phone):
    access_token = get_valid_access_token()
    url = (
        f"https://api.dotykacka.cz/v2/clouds/"
        f"{settings.DOTYKACKA_CLOUD_ID}/customers"
    )
    body = [
        {
            "_cloudId": settings.DOTYKACKA_CLOUD_ID,
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
            "_discountGroupId": settings.DOTYKACKA_DISCOUNT_GROUP_ID,
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
