"""Supervised database-backed print-package worker."""

import os
import socket
import time
from uuid import uuid4

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from operations.models import WorkerHeartbeat
from operations.services import safe_record_worker_heartbeat
from printing.services import (
    claim_next_print_job,
    complete_print_job,
    fail_print_job,
    generate_print_package,
)


class Command(BaseCommand):
    help = "Claim and generate immutable print packages under a process supervisor."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true")
        parser.add_argument("--max-jobs", type=int, default=0)
        parser.add_argument("--poll-seconds", type=float, default=2.0)
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
                    worker_type=WorkerHeartbeat.WorkerType.PRINTING,
                    worker_id=worker_id,
                    processed_count=processed,
                )
                last_heartbeat = time.monotonic()
            job = claim_next_print_job(worker_id=worker_id)
            if job is None:
                if options["once"] or options["max_jobs"]:
                    break
                time.sleep(options["poll_seconds"])
                continue
            try:
                package = generate_print_package(job=job)
            except Exception as exc:
                fail_print_job(job, exc)
                self.stderr.write(
                    f"print_job={job.pk} status=failed code={type(exc).__name__}"
                )
            else:
                complete_print_job(job)
                self.stdout.write(
                    f"print_job={job.pk} status=succeeded package={package.pk}"
                )
            processed += 1
            safe_record_worker_heartbeat(
                worker_type=WorkerHeartbeat.WorkerType.PRINTING,
                worker_id=worker_id,
                processed_count=processed,
            )
            last_heartbeat = time.monotonic()
            if options["once"]:
                break
        self.stdout.write(f"processed={processed}")
