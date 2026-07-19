import json

from django.core.management.base import BaseCommand, CommandError

from operations.health import collect_health_status


class Command(BaseCommand):
    help = "Print a redacted platform health report and optionally fail when degraded."

    def add_arguments(self, parser):
        parser.add_argument("--fail-if-degraded", action="store_true")

    def handle(self, *args, **options):
        status = collect_health_status()
        self.stdout.write(json.dumps(status, default=str, sort_keys=True))
        if options["fail_if_degraded"] and not status["ok"]:
            raise CommandError("Platform health is degraded.")
