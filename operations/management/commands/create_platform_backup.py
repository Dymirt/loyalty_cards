import json

from django.core.management.base import BaseCommand, CommandError

from operations.backups import create_platform_backup


class Command(BaseCommand):
    help = "Create checksummed database and runtime archives without provider calls."

    def add_arguments(self, parser):
        parser.add_argument("--output-root", default="")
        parser.add_argument("--label", default="scheduled")

    def handle(self, *args, **options):
        try:
            manifest_path, manifest = create_platform_backup(
                output_root=options["output_root"] or None,
                label=options["label"],
            )
        except Exception as exc:
            raise CommandError(f"Backup failed: {type(exc).__name__}") from exc
        self.stdout.write(
            json.dumps(
                {"manifest": str(manifest_path), **manifest},
                sort_keys=True,
            )
        )
