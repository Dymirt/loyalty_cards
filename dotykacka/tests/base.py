from django.contrib.auth import get_user_model

from dotykacka.models import Klient


REGISTRATION_DATA = {
    "first_name": "Jan",
    "last_name": "Kowalski",
    "email": "jan@example.test",
    "phone": "501234567",
    "barcode": "MB-12",
    "marketing_consent": "1",
}


def create_klient(card_code="MB-12", **overrides):
    values = {
        "klient_id": card_code,
        "email": "customer@example.test",
        "phone": "501234567",
        "first_name": "Test",
        "last_name": "Customer",
        "google_jwt_url": "https://wallet.example.test/save",
    }
    values.update(overrides)
    return Klient.objects.create(**values)


def create_superuser(username="operator"):
    return get_user_model().objects.create_superuser(
        username=username,
        email=f"{username}@example.test",
        password="test-only-password",
    )
