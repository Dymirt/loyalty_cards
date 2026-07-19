from django.core.management.base import BaseCommand, CommandError

from operations.models import WorkerHeartbeat
from operations.services import worker_health


class Command(BaseCommand):
    help = "Fail unless a worker type has a current database heartbeat."

    def add_arguments(self, parser):
        parser.add_argument(
            "--worker-type",
            required=True,
            choices=WorkerHeartbeat.WorkerType.values,
        )
        parser.add_argument("--max-age", type=int, default=90)

    def handle(self, *args, **options):
        if options["max_age"] <= 0:
            raise CommandError("--max-age must be positive.")
        status = worker_health(
            worker_type=options["worker_type"],
            max_age_seconds=options["max_age"],
        )
        if not status["ok"]:
            raise CommandError(
                f"Worker {options['worker_type']} heartbeat is stale or missing."
            )
        self.stdout.write(
            self.style.SUCCESS(
                f"worker={options['worker_type']} age_seconds={status['age_seconds']} status=ok"
            )
        )
