"""Verified database/runtime backup creation using only the existing stack."""

import gzip
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import tarfile
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from django.conf import settings
from django.db import connection


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_output_root(output_root=None):
    root = Path(output_root or settings.BACKUP_ROOT).resolve()
    forbidden = [
        Path(settings.MEDIA_ROOT).resolve(),
        Path(settings.STATIC_ROOT).resolve(),
        Path(settings.PRINT_PACKAGE_ROOT).resolve(),
        Path(settings.APPLE_WALLET_TEMPLATE_DIR).resolve(),
    ]
    if any(root == path or root in path.parents or path in root.parents for path in forbidden):
        raise ValueError("Backup root must be separate from media and static trees.")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    return root


def _dump_database(target):
    database = settings.DATABASES["default"]
    engine = database["ENGINE"]
    if engine == "django.db.backends.sqlite3":
        connection.ensure_connection()
        source = sqlite3.connect(str(database["NAME"]))
        destination = sqlite3.connect(str(target.with_suffix(".sqlite3.partial")))
        try:
            source.backup(destination)
        finally:
            destination.close()
            source.close()
        sqlite_path = target.with_suffix(".sqlite3.partial")
        with sqlite_path.open("rb") as source_stream, gzip.open(target, "wb", compresslevel=9) as output:
            shutil.copyfileobj(source_stream, output)
        sqlite_path.unlink()
        return
    if engine != "django.db.backends.mysql":
        raise ValueError(f"Unsupported backup database engine: {engine}")
    command = [
        "mariadb-dump",
        "--single-transaction",
        "--routines",
        "--triggers",
        "--events",
        "--default-character-set=utf8mb4",
        "--host",
        str(database.get("HOST") or "localhost"),
        "--port",
        str(database.get("PORT") or 3306),
        "--user",
        str(database["USER"]),
        str(database["NAME"]),
    ]
    environment = os.environ.copy()
    environment["MYSQL_PWD"] = str(database["PASSWORD"])
    process = None
    try:
        with tempfile.TemporaryFile() as stderr_output, gzip.open(
            target, "wb", compresslevel=9
        ) as output:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=stderr_output,
                env=environment,
            )
            if process.stdout is None:
                raise RuntimeError("Database backup did not expose a data stream.")
            shutil.copyfileobj(process.stdout, output, length=1024 * 1024)
            process.stdout.close()
            return_code = process.wait()
            stderr_output.seek(0)
            stderr_bytes = stderr_output.read()
    except Exception:
        if process is not None and process.poll() is None:
            process.kill()
            process.wait()
        target.unlink(missing_ok=True)
        raise
    if return_code:
        target.unlink(missing_ok=True)
        raise RuntimeError(
            f"Database backup failed with {type(stderr_bytes).__name__} output."
        )


def _runtime_sources():
    candidates = [
        (Path(settings.MEDIA_ROOT), "media"),
        (Path(settings.APPLE_WALLET_TEMPLATE_DIR), "wallet-template"),
        (Path(settings.PRINT_PACKAGE_ROOT), "print-packages"),
    ]
    seen = set()
    result = []
    for path, archive_name in candidates:
        resolved = path.resolve()
        if resolved in seen or not resolved.exists():
            continue
        seen.add(resolved)
        result.append((resolved, archive_name))
    return result


def create_platform_backup(*, output_root=None, label="scheduled"):
    root = _safe_output_root(output_root)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f")
    safe_label = "".join(character for character in label.lower() if character.isalnum() or character == "-")[:40] or "backup"
    prefix = f"{safe_label}-{stamp}"
    database_path = root / f"{prefix}.sql.gz"
    runtime_path = root / f"{prefix}-runtime.tar.gz"
    manifest_path = root / f"{prefix}.manifest.json"
    final_paths = (database_path, runtime_path, manifest_path)
    if any(path.exists() for path in final_paths):
        raise FileExistsError("A backup with this identifier already exists.")
    temporary_paths = tuple(
        path.with_name(f".{path.name}.partial") for path in final_paths
    )
    if any(path.exists() for path in temporary_paths):
        raise FileExistsError("A partial backup with this identifier already exists.")
    temporary_database, temporary_runtime, temporary_manifest = temporary_paths
    published_paths = []
    try:
        _dump_database(temporary_database)
        with tarfile.open(temporary_runtime, "w:gz") as archive:
            for source, archive_name in _runtime_sources():
                archive.add(source, arcname=archive_name, recursive=True)
        with gzip.open(temporary_database, "rb") as stream:
            while stream.read(1024 * 1024):
                pass
        with tarfile.open(temporary_runtime, "r:gz") as archive:
            runtime_members = len(archive.getmembers())
        manifest = {
            "created_at": datetime.now(UTC).isoformat(),
            "database": {
                "file": database_path.name,
                "sha256": sha256_file(temporary_database),
                "size_bytes": temporary_database.stat().st_size,
            },
            "runtime": {
                "file": runtime_path.name,
                "sha256": sha256_file(temporary_runtime),
                "size_bytes": temporary_runtime.stat().st_size,
                "members": runtime_members,
            },
            "format_version": 1,
        }
        temporary_manifest.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        for path in temporary_paths:
            path.chmod(0o600)
        for temporary, final in zip(temporary_paths, final_paths, strict=True):
            os.link(temporary, final)
            published_paths.append(final)
            temporary.unlink()
    except Exception:
        for path in temporary_paths:
            path.unlink(missing_ok=True)
        for path in published_paths:
            path.unlink(missing_ok=True)
        raise
    return manifest_path, manifest


def verify_backup_manifest(manifest_path):
    manifest_path = Path(manifest_path).resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    root = manifest_path.parent
    database_path = root / manifest["database"]["file"]
    runtime_path = root / manifest["runtime"]["file"]
    if sha256_file(database_path) != manifest["database"]["sha256"]:
        raise ValueError("Database backup checksum mismatch.")
    if sha256_file(runtime_path) != manifest["runtime"]["sha256"]:
        raise ValueError("Runtime backup checksum mismatch.")
    with gzip.open(database_path, "rb") as stream:
        while stream.read(1024 * 1024):
            pass
    with tarfile.open(runtime_path, "r:gz") as archive:
        member_names = {member.name.split("/", 1)[0] for member in archive.getmembers()}
    if "media" not in member_names:
        raise ValueError("Runtime backup does not contain the media root.")
    return manifest


__all__ = ["create_platform_backup", "sha256_file", "verify_backup_manifest"]
