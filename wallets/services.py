"""Stable Wallet identity and provider-neutral issuance orchestration."""

from pathlib import Path

from django.conf import settings

from cards.codes import card_number
from customers.models import Customer

from .models import WalletPass
from .registry import get_issuer


def wallet_identity(customer: Customer) -> WalletPass:
    physical_card = getattr(customer, "physical_card", None)
    wallet, _ = WalletPass.objects.get_or_create(
        customer=customer,
        defaults={"tenant": customer.tenant, "physical_card": physical_card},
    )
    return wallet


def apple_pass_path(card_code: str) -> Path:
    return (
        Path(settings.MEDIA_ROOT)
        / "output_passes"
        / f"pass_{card_number(card_code)}.pkpass"
    )


def issue_apple(customer, *, force=False, builder=None, updater=None):
    return get_issuer("apple").issue(
        customer,
        force=force,
        builder=builder,
        updater=updater,
    )


def issue_google(customer, *, url_builder=None, remote_sync=None, rest_client=None):
    return get_issuer("google").issue(
        customer,
        url_builder=url_builder,
        remote_sync=remote_sync,
        rest_client=rest_client,
    )


__all__ = [
    "apple_pass_path",
    "issue_apple",
    "issue_google",
    "wallet_identity",
]
