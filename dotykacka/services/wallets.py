"""Explicit Apple and Google Wallet generation for one loyalty customer."""

from pathlib import Path

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from dotykacka.apple_wallet_pass import build_pass
from dotykacka.card_codes import card_number
from dotykacka.google_wallet.JWT import get_wallet_url
from dotykacka.models import IntegrationConnection, Klient


def apple_pass_path(card_code: str) -> Path:
    return Path(settings.MEDIA_ROOT) / "output_passes" / f"pass_{card_number(card_code)}.pkpass"


def ensure_apple_wallet_pass(klient: Klient, *, force: bool = False) -> Path:
    """Generate a missing pass, while preserving every existing legacy pass by default."""

    pass_path = apple_pass_path(klient.klient_id)
    if pass_path.is_file() and not force:
        return pass_path

    generated_path = Path(build_pass(card_number(klient.klient_id)))
    return generated_path


def generate_google_wallet_for_klient(klient: Klient) -> str:
    try:
        connection = IntegrationConnection.objects.get(
            tenant=klient.tenant,
            provider=IntegrationConnection.Provider.GOOGLE_WALLET,
            enabled=True,
        )
    except IntegrationConnection.DoesNotExist as exc:
        raise ImproperlyConfigured(
            "Google Wallet is not enabled for this tenant."
        ) from exc
    issuer_id = connection.configuration.get("issuer_id", "")
    class_suffix = connection.configuration.get("class_suffix", "")
    number = card_number(klient.klient_id)
    customer_name = " ".join(
        part for part in (klient.first_name, klient.last_name) if part
    )
    wallet_url = get_wallet_url(
        name=customer_name,
        customer_id=klient.klient_id,
        issuer_id=issuer_id,
        class_suffix=class_suffix,
        customer_image_url=(
            f"{settings.APP_BASE_URL}/media/cropped_images/cropped_image_{number}.jpg"
        ),
    )
    klient.google_jwt_url = wallet_url
    klient.save(update_fields=["google_jwt_url"])
    return wallet_url
