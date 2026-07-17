"""Provider-neutral POS customer contract."""

from typing import Protocol

from integrations.contracts import ProviderResult


class PosCustomerAdapter(Protocol):
    def upsert_customer(self, customer) -> ProviderResult: ...

    def list_customers(self) -> list[dict]: ...

    def test_connection(self) -> ProviderResult: ...


__all__ = ["PosCustomerAdapter"]
