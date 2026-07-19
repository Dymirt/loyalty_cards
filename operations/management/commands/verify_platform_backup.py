from django.core.management.base import BaseCommand, CommandError

from operations.backups import verify_backup_manifest


class Command(BaseCommand):
    help = "Verify checksums and archive integrity for a platform backup manifest."

    def add_arguments(self, parser):
        parser.add_argument("manifest")

    def handle(self, *args, **options):
        try:
            manifest = verify_backup_manifest(options["manifest"])
        except Exception as exc:
            raise CommandError(f"Backup verification failed: {type(exc).__name__}") from exc
        self.stdout.write(
            self.style.SUCCESS(
                f"backup=ok format_version={manifest['format_version']}"
            )
        )
