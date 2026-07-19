"""Redacted application readiness and detailed superuser health projections."""

import tempfile
from pathlib import Path

from django.conf import settings
from django.db import connection

from dotykacka.models import IntegrationConnection

from .models import WorkerHeartbeat
from .services import worker_health


def database_health():
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            value = cursor.fetchone()[0]
    except Exception as exc:
        return {"ok": False, "code": type(exc).__name__}
    return {"ok": value == 1, "code": "ok"}


def storage_health(path):
    root = Path(path)
    probe_dir = root / ".health"
    try:
        probe_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w+b",
            dir=probe_dir,
            prefix="probe-",
            delete=True,
        ) as probe:
            payload = b"loyalty-storage-health"
            probe.write(payload)
            probe.flush()
            probe.seek(0)
            valid = probe.read() == payload
    except Exception as exc:
        return {"ok": False, "code": type(exc).__name__}
    return {"ok": valid, "code": "ok" if valid else "read_mismatch"}


def provider_configuration_health():
    apple_files = [
        settings.APPLE_WALLET_TEMPLATE_DIR / "AppleWWDR.pem",
        settings.APPLE_WALLET_TEMPLATE_DIR / "certificate.pem",
        settings.APPLE_WALLET_TEMPLATE_DIR / "key.pem",
    ]
    try:
        active_connections = IntegrationConnection.objects.filter(enabled=True)
        tenant_connections = {
            "configured": None,
            "active": active_connections.count(),
            "with_error": active_connections.exclude(last_error_code="").count(),
        }
    except Exception as exc:
        tenant_connections = {
            "configured": None,
            "active": None,
            "with_error": None,
            "code": type(exc).__name__,
        }
    return {
        "dotykacka_connector": {
            "configured": bool(
                settings.DOTYKACKA_CONNECTOR_CLIENT_ID
                and settings.DOTYKACKA_CONNECTOR_CLIENT_SECRET
            )
        },
        "google_wallet": {
            "configured": bool(
                settings.GOOGLE_WALLET_ISSUER_ID
                and settings.GOOGLE_WALLET_SERVICE_ACCOUNT_FILE.is_file()
            )
        },
        "apple_wallet": {
            "configured": bool(
                settings.APPLE_WALLET_PASS_TYPE_IDENTIFIER
                and settings.APPLE_WALLET_TEAM_IDENTIFIER
                and all(path.is_file() for path in apple_files)
            )
        },
        "smtp": {
            "configured": bool(
                settings.EMAIL_HOST
                or settings.EMAIL_BACKEND.endswith("console.EmailBackend")
                or settings.EMAIL_BACKEND.endswith("locmem.EmailBackend")
            )
        },
        "tenant_connections": tenant_connections,
    }


def collect_health_status():
    worker_max_age = settings.WORKER_HEARTBEAT_MAX_AGE_SECONDS
    workers = {}
    for worker_type in (
        WorkerHeartbeat.WorkerType.INTEGRATION,
        WorkerHeartbeat.WorkerType.PRINTING,
        WorkerHeartbeat.WorkerType.MONITOR,
    ):
        try:
            workers[worker_type] = worker_health(
                worker_type=worker_type,
                max_age_seconds=worker_max_age,
            )
        except Exception as exc:
            workers[worker_type] = {
                "ok": False,
                "worker_type": worker_type,
                "age_seconds": None,
                "code": type(exc).__name__,
            }
    components = {
        "database": database_health(),
        "media_storage": storage_health(settings.MEDIA_ROOT),
        "print_storage": storage_health(settings.PRINT_PACKAGE_ROOT),
        "workers": workers,
        "providers": provider_configuration_health(),
    }
    critical_ok = all(
        components[name]["ok"]
        for name in ("database", "media_storage", "print_storage")
    ) and all(item["ok"] for item in workers.values())
    return {"ok": critical_ok, "components": components}


__all__ = [
    "collect_health_status",
    "database_health",
    "provider_configuration_health",
    "storage_health",
]
