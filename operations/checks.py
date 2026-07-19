"""Configuration checks for the production hardening boundary."""

from pathlib import Path
from ipaddress import ip_network

from django.conf import settings
from django.core.checks import Error, Tags, register


@register(Tags.security)
def operational_security_configuration(app_configs, **kwargs):
    errors = []
    expected_middleware = "operations.middleware.PlatformSecurityMiddleware"
    if expected_middleware not in settings.MIDDLEWARE:
        errors.append(
            Error(
                "Platform security middleware is not enabled.",
                id="operations.E001",
            )
        )
    for name in (
        "DATA_UPLOAD_MAX_MEMORY_SIZE",
        "FILE_UPLOAD_MAX_MEMORY_SIZE",
        "DATA_UPLOAD_MAX_NUMBER_FIELDS",
        "DATA_UPLOAD_MAX_NUMBER_FILES",
        "WORKER_HEARTBEAT_MAX_AGE_SECONDS",
    ):
        if not isinstance(getattr(settings, name, None), int) or getattr(settings, name) <= 0:
            errors.append(
                Error(f"{name} must be a positive integer.", id="operations.E002")
            )
    media_root = Path(settings.MEDIA_ROOT).resolve()
    static_root = Path(settings.STATIC_ROOT).resolve()
    if media_root == static_root or media_root in static_root.parents or static_root in media_root.parents:
        errors.append(
            Error(
                "MEDIA_ROOT and STATIC_ROOT must be separate directory trees.",
                id="operations.E003",
            )
        )
    for value in settings.LOYALTY_TRUSTED_PROXY_CIDRS:
        try:
            ip_network(value, strict=False)
        except ValueError:
            errors.append(
                Error(
                    f"LOYALTY_TRUSTED_PROXY_CIDRS contains an invalid network: {value}",
                    id="operations.E004",
                )
            )
    backup_root = Path(settings.BACKUP_ROOT).resolve()
    protected_roots = {
        "MEDIA_ROOT": media_root,
        "STATIC_ROOT": static_root,
        "PRINT_PACKAGE_ROOT": Path(settings.PRINT_PACKAGE_ROOT).resolve(),
        "APPLE_WALLET_TEMPLATE_DIR": Path(settings.APPLE_WALLET_TEMPLATE_DIR).resolve(),
    }
    for setting_name, protected_root in protected_roots.items():
        if (
            backup_root == protected_root
            or backup_root in protected_root.parents
            or protected_root in backup_root.parents
        ):
            errors.append(
                Error(
                    f"BACKUP_ROOT and {setting_name} must be separate directory trees.",
                    id="operations.E005",
                )
            )
    return errors


__all__ = ["operational_security_configuration"]
