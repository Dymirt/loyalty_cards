import gzip
from io import BytesIO
import json
import tarfile
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from django.conf import settings
from django.test import SimpleTestCase, override_settings

from operations.backups import (
    _dump_database,
    _safe_output_root,
    sha256_file,
    verify_backup_manifest,
)


class BackupVerificationTests(SimpleTestCase):
    def test_production_timer_uses_the_active_release_and_is_deployed(self):
        project_root = Path(__file__).parents[2]
        service = (
            project_root / "deploy/systemd/loyalty-backup.service"
        ).read_text(encoding="utf-8")
        deployment = (
            project_root / "deploy/production/deploy.sh"
        ).read_text(encoding="utf-8")

        self.assertIn("User=www-data", service)
        self.assertIn("WorkingDirectory=/var/www/loyalty_platform/current", service)
        self.assertIn(
            "/var/www/loyalty_platform/current/.venv/bin/python", service
        )
        self.assertIn("loyalty-backup.timer", deployment)
        self.assertIn("systemctl enable --now loyalty-backup.timer", deployment)

    def test_backup_root_cannot_overlap_runtime_sources(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            media = root / "media"
            media.mkdir()
            with override_settings(
                MEDIA_ROOT=media,
                STATIC_ROOT=root / "static",
                PRINT_PACKAGE_ROOT=root / "printing",
                APPLE_WALLET_TEMPLATE_DIR=root / "wallet-template",
            ):
                with self.assertRaisesMessage(ValueError, "must be separate"):
                    _safe_output_root(media / "backups")

    def test_mariadb_subprocess_output_is_gzip_compressed(self):
        with TemporaryDirectory() as directory:
            target = Path(directory) / "backup.sql.gz"
            process = Mock()
            process.stdout = BytesIO(b"CREATE TABLE example (id integer);\n")
            process.wait.return_value = 0
            process.poll.return_value = 0
            database = {
                "ENGINE": "django.db.backends.mysql",
                "NAME": "test_django",
                "USER": "test-user",
                "PASSWORD": "not-a-real-password",
                "HOST": "database",
                "PORT": "3306",
            }
            with (
                patch.object(settings, "DATABASES", {"default": database}),
                patch("operations.backups.subprocess.Popen", return_value=process),
            ):
                _dump_database(target)

            with gzip.open(target, "rb") as stream:
                self.assertEqual(
                    stream.read(), b"CREATE TABLE example (id integer);\n"
                )

    def test_checksums_and_archive_structure_are_verified(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "backup.sql.gz"
            runtime = root / "backup-runtime.tar.gz"
            with gzip.open(database, "wb") as stream:
                stream.write(b"CREATE TABLE example (id integer);\n")
            media = root / "media"
            media.mkdir()
            (media / "marker.txt").write_text("runtime", encoding="utf-8")
            with tarfile.open(runtime, "w:gz") as archive:
                archive.add(media, arcname="media")
            manifest = root / "backup.manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "format_version": 1,
                        "database": {
                            "file": database.name,
                            "sha256": sha256_file(database),
                            "size_bytes": database.stat().st_size,
                        },
                        "runtime": {
                            "file": runtime.name,
                            "sha256": sha256_file(runtime),
                            "size_bytes": runtime.stat().st_size,
                            "members": 2,
                        },
                    }
                ),
                encoding="utf-8",
            )
            self.assertEqual(verify_backup_manifest(manifest)["format_version"], 1)

            database.write_bytes(database.read_bytes() + b"tampered")
            with self.assertRaisesMessage(ValueError, "checksum mismatch"):
                verify_backup_manifest(manifest)
