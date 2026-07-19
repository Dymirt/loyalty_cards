#!/usr/bin/env python3
"""Convert the protected legacy export into the production platform environment."""

from __future__ import annotations

import argparse
import base64
import os
import re
import shlex
from pathlib import Path


KEY_RE = re.compile(r"^(?P<key>[A-Za-z_][A-Za-z0-9_]*)=(?P<value>.*)$")


def decoded(value: str) -> str:
    if not value.strip():
        return ""
    parsed = shlex.split(value, posix=True)
    return parsed[0] if parsed else ""


def encoded(value: str) -> str:
    return shlex.quote(value)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("environment", type=Path)
    args = parser.parse_args()

    path = args.environment
    lines = path.read_text(encoding="utf-8").splitlines()
    positions: dict[str, int] = {}
    values: dict[str, str] = {}
    for index, line in enumerate(lines):
        match = KEY_RE.match(line)
        if not match:
            continue
        key = match.group("key")
        positions[key] = index
        values[key] = decoded(match.group("value"))

    def set_value(key: str, value: str) -> None:
        rendered = f"{key}={encoded(value)}"
        if key in positions:
            lines[positions[key]] = rendered
        else:
            positions[key] = len(lines)
            lines.append(rendered)
        values[key] = value

    production_values = {
        "DJANGO_DEBUG": "False",
        "DJANGO_ALLOWED_HOSTS": "club.mbstudio.online,localhost,127.0.0.1",
        "DJANGO_CSRF_TRUSTED_ORIGINS": "https://club.mbstudio.online",
        "DJANGO_TRUST_X_FORWARDED_PROTO": "True",
        "DJANGO_SECURE_SSL_REDIRECT": "True",
        "DJANGO_SESSION_COOKIE_SECURE": "True",
        "DJANGO_CSRF_COOKIE_SECURE": "True",
        "DJANGO_SECURE_HSTS_SECONDS": "31536000",
        "DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS": "True",
        "DJANGO_SECURE_HSTS_PRELOAD": "True",
        "APP_BASE_URL": "https://club.mbstudio.online",
        "DB_ENGINE": "django.db.backends.mysql",
        "DB_HOST": "localhost",
        "DB_PORT": "3306",
        "MEDIA_ROOT": "/var/www/turnkey_project/media",
        "PRINT_PACKAGE_ROOT": "/var/www/loyalty_platform/shared/print-packages",
        "BACKUP_ROOT": "/var/backups/loyalty-platform",
        "GOOGLE_WALLET_SERVICE_ACCOUNT_FILE": (
            "/var/www/loyalty_platform/shared/secrets/google-wallet-service-account.json"
        ),
        "APPLE_WALLET_TEMPLATE_DIR": (
            "/var/www/loyalty_platform/shared/mypass_template"
        ),
        "LOYALTY_ALLOWED_HOSTS_FILE": "",
        "TURNKEY_ALLOWED_HOSTS_FILE": "",
        "LOYALTY_LOG_LEVEL": "INFO",
    }
    for key, value in production_values.items():
        set_value(key, value)

    wallet_origins = [
        item.strip()
        for item in values.get("GOOGLE_WALLET_ORIGINS", "").split(",")
        if item.strip()
    ]
    if "https://club.mbstudio.online" not in wallet_origins:
        wallet_origins.append("https://club.mbstudio.online")
    set_value("GOOGLE_WALLET_ORIGINS", ",".join(wallet_origins))

    if not values.get("TENANT_SECRETS_ENCRYPTION_KEYS"):
        key = base64.urlsafe_b64encode(os.urandom(32)).decode("ascii")
        set_value("TENANT_SECRETS_ENCRYPTION_KEYS", key)

    required = (
        "DJANGO_SECRET_KEY",
        "DB_NAME",
        "DB_USER",
        "DB_PASSWORD",
        "DOTYKACKA_AUTHORIZATION_TOKEN",
        "BREVO_API_KEY",
        "EMAIL_HOST_PASSWORD",
        "GOOGLE_WALLET_ISSUER_ID",
        "APPLE_WALLET_PASS_TYPE_IDENTIFIER",
        "APPLE_WALLET_TEAM_IDENTIFIER",
        "TENANT_SECRETS_ENCRYPTION_KEYS",
    )
    missing = [key for key in required if not values.get(key)]
    if missing:
        parser.error("required production values are empty: " + ", ".join(missing))

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    path.chmod(0o600)
    print(f"production environment configured ({len(values)} keys; values not displayed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
