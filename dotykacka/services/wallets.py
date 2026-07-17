"""Explicit tenant-aware Apple and Google Wallet generation."""

import re
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from dotykacka.card_codes import card_number
from dotykacka.google_wallet.JWT import get_wallet_url
from dotykacka.models import CardDesign, IntegrationConnection, Klient, WalletPass

from .apple_wallet import build_apple_pass, update_wallet_apple_artifact


def wallet_identity(klient: Klient) -> WalletPass:
    physical_card = getattr(klient, "physical_card", None)
    wallet, _ = WalletPass.objects.get_or_create(
        customer=klient,
        defaults={
            "tenant": klient.tenant,
            "physical_card": physical_card,
        },
    )
    return wallet


def apple_pass_path(card_code: str) -> Path:
    return Path(settings.MEDIA_ROOT) / "output_passes" / f"pass_{card_number(card_code)}.pkpass"


def ensure_apple_wallet_pass(klient: Klient, *, force: bool = False) -> Path:
    """Generate a missing pass without overwriting a legacy or versioned artifact."""

    wallet = wallet_identity(klient)
    if wallet.apple_pass_path:
        stored_path = Path(settings.MEDIA_ROOT) / wallet.apple_pass_path
        if stored_path.is_file() and not force:
            return stored_path
    legacy_path = apple_pass_path(klient.klient_id)
    if legacy_path.is_file() and not force:
        if not wallet.apple_pass_path:
            wallet.apple_pass_path = str(legacy_path.relative_to(settings.MEDIA_ROOT))
            wallet.save(update_fields=("apple_pass_path", "updated_at"))
        return legacy_path

    design = CardDesign.objects.filter(tenant=klient.tenant).first()
    if design is None:
        raise ImproperlyConfigured("No published card design exists for this tenant.")
    generated_path, artifact = build_apple_pass(
        customer=klient,
        wallet=wallet,
        design=design,
    )
    update_wallet_apple_artifact(wallet, artifact)
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
    wallet = wallet_identity(klient)
    expected_object_id = f"{issuer_id}.{re.sub(r'[^A-Za-z0-9._-]', '_', klient.klient_id)}"
    if wallet.google_object_id and wallet.google_object_id != expected_object_id:
        raise ImproperlyConfigured(
            "The stored Google Wallet object belongs to a different issuer configuration."
        )
    if not wallet.google_object_id:
        wallet.google_object_id = expected_object_id
    number = card_number(klient.klient_id)
    customer_name = " ".join(
        part for part in (klient.first_name, klient.last_name) if part
    )
    wallet_url = get_wallet_url(
        name=customer_name,
        customer_id=klient.klient_id,
        issuer_id=issuer_id,
        class_suffix=class_suffix,
        object_id=wallet.google_object_id,
        customer_image_url=(
            f"{settings.APP_BASE_URL}/media/cropped_images/cropped_image_{number}.jpg"
        ),
        image_description=f"Karta lojalnościowa {klient.tenant.brand.public_name}",
    )
    wallet.google_save_url = wallet_url
    wallet.save(update_fields=("google_object_id", "google_save_url", "updated_at"))
    klient.google_jwt_url = wallet_url
    klient.save(update_fields=["google_jwt_url"])
    return wallet_url
