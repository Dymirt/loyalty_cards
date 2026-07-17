"""Deprecated compatibility import for the external-call-blocking test runner."""

from loyalty_platform.test_runner import (  # noqa: F401
    NoExternalCallsDiscoverRunner,
    _blocked_external_call,
)
