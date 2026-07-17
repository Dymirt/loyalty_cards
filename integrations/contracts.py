"""Shared errors and results used at provider boundaries."""

from dataclasses import dataclass, field


class IntegrationError(RuntimeError):
    error_code = "integration_error"

    def __init__(self, message="Integration operation failed.", *, error_code=None):
        super().__init__(message)
        if error_code:
            self.error_code = error_code


class RetryableIntegrationError(IntegrationError):
    error_code = "provider_retryable"

    def __init__(self, message="Provider is temporarily unavailable.", *, error_code=None, retry_after=None):
        super().__init__(message, error_code=error_code)
        self.retry_after = retry_after


class IntegrationConfigurationError(IntegrationError):
    error_code = "configuration_required"


class IntegrationAuthenticationError(IntegrationError):
    error_code = "authentication_required"


@dataclass(frozen=True)
class ProviderResult:
    remote_id: str = ""
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class SystemCheckResult:
    """Redacted result rendered on the platform diagnostics page."""

    ok: bool
    summary: str
    details: tuple[str, ...] = ()


__all__ = [
    "IntegrationAuthenticationError",
    "IntegrationConfigurationError",
    "IntegrationError",
    "ProviderResult",
    "RetryableIntegrationError",
    "SystemCheckResult",
]
