"""Deprecated compatibility imports for :mod:`tenants.authorization`."""

from tenants.authorization import (
    can_access_tenant,
    can_manage_card_designs,
    can_manage_integrations,
    get_default_tenant,
    get_public_tenant,
    superuser_required,
)


__all__ = [
    "can_access_tenant",
    "can_manage_card_designs",
    "can_manage_integrations",
    "get_default_tenant",
    "get_public_tenant",
    "superuser_required",
]
