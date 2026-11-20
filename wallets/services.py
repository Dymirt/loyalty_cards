"""Stable Wallet identity and provider-neutral issuance orchestration."""

from pathlib import Path

from django.conf import settings

from cards.codes import card_number
from customers.models import Customer

from .models import WalletPass
from .registry import get_issuer


def wallet_identity(customer: Customer, *, card_design=None) -> WalletPass:
    physical_card = getattr(customer, "physical_card", None)
    wallet, _ = WalletPass.objects.get_or_create(
        customer=customer,
        defaults={
            "tenant": customer.tenant,
            "physical_card": physical_card,
            "card_design": card_design,
        },
    )
    if card_design is not None:
        if card_design.tenant_id != customer.tenant_id:
            raise ValueError("The selected card design belongs to another tenant.")
        if wallet.card_design_id and wallet.card_design_id != card_design.pk:
            raise ValueError("The Wallet card design is immutable after issuance.")
        if wallet.card_design_id is None:
            wallet.card_design = card_design
            wallet.full_clean()
            wallet.save(update_fields=("card_design", "updated_at"))
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
