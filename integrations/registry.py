"""In-process registries keep provider dependencies pointing inward."""

from dataclasses import dataclass
from typing import Callable


JobHandler = Callable[[object], object]

_job_handlers: dict[str, JobHandler] = {}
_settings_providers: dict[str, "SettingsProvider"] = {}
_system_connection_checks: dict[str, "SystemConnectionCheck"] = {}


@dataclass(frozen=True)
class SettingsProvider:
    provider: str
    title: str
    description: str
    form_class: type
    tester: Callable[[object], object] | None = None
    secret_name: str = ""
    secret_label: str = ""
    tenant_testable: bool = True


@dataclass(frozen=True)
class SystemConnectionCheck:
    key: str
    title: str
    description: str
    checker: Callable[[], object]


def register_job_handler(kind: str, handler: JobHandler) -> None:
    _job_handlers[kind] = handler


def get_job_handler(kind: str) -> JobHandler:
    try:
        return _job_handlers[kind]
    except KeyError as exc:
        raise LookupError(f"No integration job handler is registered for {kind}.") from exc


def register_settings_provider(provider: SettingsProvider) -> None:
    _settings_providers[provider.provider] = provider


def settings_providers() -> tuple[SettingsProvider, ...]:
    return tuple(_settings_providers[key] for key in sorted(_settings_providers))


def register_system_connection_check(check: SystemConnectionCheck) -> None:
    _system_connection_checks[check.key] = check


def system_connection_checks() -> tuple[SystemConnectionCheck, ...]:
    return tuple(
        _system_connection_checks[key] for key in sorted(_system_connection_checks)
    )


def reset_registries_for_tests() -> None:
    _job_handlers.clear()
    _settings_providers.clear()
    _system_connection_checks.clear()


__all__ = [
    "SettingsProvider",
    "SystemConnectionCheck",
    "get_job_handler",
    "register_job_handler",
    "register_settings_provider",
    "register_system_connection_check",
    "settings_providers",
    "system_connection_checks",
]
