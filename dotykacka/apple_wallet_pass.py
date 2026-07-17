"""Compatibility imports for callers moving to tenant-aware Wallet services."""

from dotykacka.services.apple_wallet import generate_manifest, sign_manifest
from dotykacka.services.wallets import ensure_apple_wallet_pass


def build_pass(card_number):
    """Generate one default-tenant customer pass through the shared service."""

    from dotykacka.models import Klient
    from dotykacka.tenancy import get_default_tenant

    tenant = get_default_tenant()
    customer = Klient.objects.get(tenant=tenant, klient_id=f"{tenant.card_prefix}-{card_number}")
    return str(ensure_apple_wallet_pass(customer, force=True))


__all__ = ("build_pass", "generate_manifest", "sign_manifest")
