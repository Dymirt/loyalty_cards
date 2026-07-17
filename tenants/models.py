"""Tenant-domain model imports.

The legacy ``dotykacka`` app retains Django state and database-table ownership
during Phase 5.  These aliases give new code an owning-domain import path
without registering a second model or touching stored data.
"""

from dotykacka.models import (
    Tenant,
    TenantBrand,
    TenantBrandRevision,
    TenantMembership,
)


__all__ = [
    "Tenant",
    "TenantBrand",
    "TenantBrandRevision",
    "TenantMembership",
]
