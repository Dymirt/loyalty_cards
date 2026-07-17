"""Provider-neutral contact synchronization contract."""

from typing import Protocol

from integrations.contracts import ProviderResult


class ContactSyncAdapter(Protocol):
    def upsert_contact(self, customer) -> ProviderResult: ...

    def test_connection(self) -> ProviderResult: ...


__all__ = ["ContactSyncAdapter"]
