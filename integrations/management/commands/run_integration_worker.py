"""Supervised database-backed integration worker."""

import os
import socket
import time
from uuid import uuid4

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from integrations.registry import get_job_handler
from integrations.services import claim_next_job, complete_job, fail_job
from operations.models import WorkerHeartbeat
from operations.services import safe_record_worker_heartbeat


class Command(BaseCommand):
    help = "Claim and execute durable provider jobs. Run under a process supervisor."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true")
        parser.add_argument(
            "--max-jobs",
            type=int,
            default=0,
            help="Exit after this many jobs; 0 keeps polling under a supervisor.",
        )
        parser.add_argument("--poll-seconds", type=float, default=2.0)
        parser.add_argument("--kind", action="append", default=[])
        parser.add_argument("--worker-id", default="")

    def handle(self, *args, **options):
        if options["max_jobs"] < 0:
            raise CommandError("--max-jobs cannot be negative.")
        if options["poll_seconds"] <= 0:
            raise CommandError("--poll-seconds must be greater than zero.")
        worker_id = options["worker_id"] or (
            f"{socket.gethostname()}:{os.getpid()}:{uuid4().hex[:8]}"
        )
        processed = 0
        last_heartbeat = 0.0
        while not options["max_jobs"] or processed < options["max_jobs"]:
            if time.monotonic() - last_heartbeat >= settings.WORKER_HEARTBEAT_INTERVAL_SECONDS:
                safe_record_worker_heartbeat(
                    worker_type=WorkerHeartbeat.WorkerType.INTEGRATION,
                    worker_id=worker_id,
                    processed_count=processed,
                    safe_metadata={"kind_filters": ",".join(options["kind"])},
                )
                last_heartbeat = time.monotonic()
            job = claim_next_job(worker_id=worker_id, kinds=options["kind"])
            if job is None:
                if options["once"] or options["max_jobs"]:
                    break
                time.sleep(options["poll_seconds"])
                continue
            try:
                handler = get_job_handler(job.kind)
                handler(job)
            except Exception as exc:
                fail_job(job, exc)
                self.stderr.write(
                    f"job={job.pk} kind={job.kind} status=failed code="
                    f"{getattr(exc, 'error_code', type(exc).__name__)}"
                )
            else:
                complete_job(job)
                self.stdout.write(f"job={job.pk} kind={job.kind} status=succeeded")
            processed += 1
            safe_record_worker_heartbeat(
                worker_type=WorkerHeartbeat.WorkerType.INTEGRATION,
                worker_id=worker_id,
                processed_count=processed,
                safe_metadata={"kind_filters": ",".join(options["kind"])},
            )
            last_heartbeat = time.monotonic()
            if options["once"]:
                break
        self.stdout.write(f"processed={processed}")
