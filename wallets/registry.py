"""Wallet provider registry populated by provider AppConfig.ready hooks."""

_issuers = {}


def register_issuer(provider, issuer):
    _issuers[provider] = issuer


def get_issuer(provider):
    try:
        return _issuers[provider]
    except KeyError as exc:
        raise LookupError(f"No Wallet issuer is registered for {provider}.") from exc


__all__ = ["get_issuer", "register_issuer"]
