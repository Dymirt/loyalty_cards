"""Explicit Apple and Google Wallet generation for one loyalty customer."""

from pathlib import Path

from django.conf import settings

from dotykacka.apple_wallet_pass import build_pass
from dotykacka.card_codes import card_number
from dotykacka.google_wallet.JWT import get_wallet_url
from dotykacka.models import Klient


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
    number = card_number(klient.klient_id)
    customer_name = " ".join(
        part for part in (klient.first_name, klient.last_name) if part
    )
    wallet_url = get_wallet_url(
        name=customer_name,
        customer_id=klient.klient_id,
        customer_image_url=(
            f"{settings.APP_BASE_URL}/media/cropped_images/cropped_image_{number}.jpg"
        ),
    )
    klient.google_jwt_url = wallet_url
    klient.save(update_fields=["google_jwt_url"])
    return wallet_url
