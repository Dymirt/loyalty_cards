import os
import socket
import time
from uuid import uuid4

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from operations.models import WorkerHeartbeat
from operations.monitoring import scan_operational_alerts
from operations.services import safe_record_worker_heartbeat


class Command(BaseCommand):
    help = "Continuously scan database-only operational rules under a supervisor."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true")
        parser.add_argument("--max-scans", type=int, default=0)
        parser.add_argument(
            "--poll-seconds",
            type=float,
            default=float(settings.OPERATIONS_MONITOR_INTERVAL_SECONDS),
        )
        parser.add_argument("--worker-id", default="")

    def handle(self, *args, **options):
        if options["max_scans"] < 0:
            raise CommandError("--max-scans cannot be negative.")
        if options["poll_seconds"] <= 0:
            raise CommandError("--poll-seconds must be greater than zero.")
        worker_id = options["worker_id"] or (
            f"{socket.gethostname()}:{os.getpid()}:{uuid4().hex[:8]}"
        )
        scans = 0
        while not options["max_scans"] or scans < options["max_scans"]:
            safe_record_worker_heartbeat(
                worker_type=WorkerHeartbeat.WorkerType.MONITOR,
                worker_id=worker_id,
                processed_count=scans,
            )
            try:
                result = scan_operational_alerts()
            except Exception as exc:
                self.stderr.write(f"monitor status=failed code={type(exc).__name__}")
            else:
                scans += 1
                safe_record_worker_heartbeat(
                    worker_type=WorkerHeartbeat.WorkerType.MONITOR,
                    worker_id=worker_id,
                    processed_count=scans,
                )
                self.stdout.write(
                    f"monitor status=succeeded active={result['active']} resolved={result['resolved']}"
                )
            if options["once"]:
                break
            time.sleep(options["poll_seconds"])
        self.stdout.write(f"scans={scans}")
