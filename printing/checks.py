"""Deployment checks for protected production-package storage."""

from pathlib import Path

from django.conf import settings
from django.core.checks import Error, Tags, register


@register(Tags.security)
def protected_print_package_root(app_configs, **kwargs):
    package_root = Path(settings.PRINT_PACKAGE_ROOT).resolve()
    public_roots = {
        "MEDIA_ROOT": Path(settings.MEDIA_ROOT).resolve(),
        "STATIC_ROOT": Path(settings.STATIC_ROOT).resolve(),
    }
    errors = []
    for setting_name, public_root in public_roots.items():
        if (
            package_root == public_root
            or public_root in package_root.parents
            or package_root in public_root.parents
        ):
            errors.append(
                Error(
                    f"PRINT_PACKAGE_ROOT must not be inside {setting_name}.",
                    hint="Use a protected filesystem path served only by the printing download view.",
                    id="printing.E001",
                )
            )
    return errors
