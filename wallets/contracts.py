"""Provider-neutral Wallet issuance contract."""

from typing import Protocol


class WalletIssuer(Protocol):
    provider: str

    def issue(self, customer, *, force=False): ...


__all__ = ["WalletIssuer"]
