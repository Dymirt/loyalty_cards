"""Safely preview, requeue and verify failed customer synchronizations."""

import time
from collections import Counter

from django.core.management.base import BaseCommand, CommandError

from customers.models import CustomerExternalIdentity
from integrations.models import IntegrationJob
from integrations.services import retry_failed_job
from pos_dotykacka.jobs import CUSTOMER_UPSERT_JOB
from pos_dotykacka.services import PROVIDER


class Command(BaseCommand):
    help = (
        "Preview or requeue failed Dotykačka customer synchronizations. "
        "Without --error-code, only legacy HTTPError failures are selected."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--job-id",
            action="append",
            type=int,
            default=[],
            help="Limit the operation to this job ID; may be repeated.",
        )
        parser.add_argument(
            "--error-code",
            action="append",
            default=[],
            help="Select this stored error code; may be repeated.",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Requeue matching jobs. Without this flag the command is read-only.",
        )
        parser.add_argument(
            "--expect-count",
            type=int,
            help="Abort unless exactly this many jobs match.",
        )
        parser.add_argument(
            "--require-job-id",
            action="append",
            type=int,
            default=[],
            help="Abort unless this job ID matches; may be repeated.",
        )
        parser.add_argument(
            "--wait-seconds",
            type=int,
            default=0,
            help=(
                "After requeueing, wait for every selected job and external identity "
                "to be synchronized (maximum 300 seconds)."
            ),
        )

    def handle(self, *args, **options):
        wait_seconds = options["wait_seconds"]
        if wait_seconds < 0 or wait_seconds > 300:
            raise CommandError("--wait-seconds must be between 0 and 300.")
        if wait_seconds and not options["apply"]:
            raise CommandError("--wait-seconds requires --apply.")
        error_codes = options["error_code"] or ["HTTPError"]
        queryset = IntegrationJob.objects.filter(
            kind=CUSTOMER_UPSERT_JOB,
            status=IntegrationJob.Status.FAILED,
            last_error_code__in=error_codes,
        ).order_by("pk")
        if options["job_id"]:
            queryset = queryset.filter(pk__in=options["job_id"])
        jobs = list(queryset)
        job_ids = [job.pk for job in jobs]
        rendered_ids = ",".join(str(job_id) for job_id in job_ids) or "none"
        self.stdout.write(f"matched={len(job_ids)} job_ids={rendered_ids}")
        expected_count = options["expect_count"]
        if expected_count is not None and len(job_ids) != expected_count:
            raise CommandError(
                f"Expected {expected_count} matching jobs, found {len(job_ids)}."
            )
        missing_required_ids = sorted(set(options["require_job_id"]) - set(job_ids))
        if missing_required_ids:
            rendered_missing = ",".join(str(job_id) for job_id in missing_required_ids)
            raise CommandError(f"Required job IDs did not match: {rendered_missing}.")
        if not options["apply"]:
            self.stdout.write("dry-run: pass --apply to requeue these jobs")
            return
        for job in jobs:
            retry_failed_job(job=job)
        self.stdout.write(self.style.SUCCESS(f"requeued={len(job_ids)}"))
        if wait_seconds and job_ids:
            self._wait_for_success(
                jobs=jobs,
                wait_seconds=wait_seconds,
            )

    def _wait_for_success(self, *, jobs, wait_seconds):
        job_ids = [job.pk for job in jobs]
        customer_ids = {job.payload.get("customer_id") for job in jobs}
        if None in customer_ids:
            raise CommandError("A selected job has no customer_id payload.")
        deadline = time.monotonic() + wait_seconds
        while True:
            states = list(
                IntegrationJob.objects.filter(pk__in=job_ids)
                .order_by("pk")
                .values_list("pk", "status", "last_error_code")
            )
            if len(states) != len(job_ids):
                raise CommandError("A selected integration job disappeared.")
            failed = [row for row in states if row[1] == IntegrationJob.Status.FAILED]
            if failed:
                rendered = ",".join(
                    f"{job_id}:{error_code or 'unknown'}"
                    for job_id, _status, error_code in failed
                )
                raise CommandError(f"Synchronization failed: {rendered}.")
            if all(row[1] == IntegrationJob.Status.SUCCEEDED for row in states):
                synchronized_customer_ids = set(
                    CustomerExternalIdentity.objects.filter(
                        customer_id__in=customer_ids,
                        provider=PROVIDER,
                        sync_status=CustomerExternalIdentity.SyncStatus.SYNCED,
                    )
                    .exclude(remote_id__isnull=True)
                    .exclude(remote_id="")
                    .values_list("customer_id", flat=True)
                )
                missing_customer_ids = sorted(customer_ids - synchronized_customer_ids)
                if missing_customer_ids:
                    rendered = ",".join(
                        str(customer_id) for customer_id in missing_customer_ids
                    )
                    raise CommandError(
                        f"Jobs succeeded without external customer IDs: {rendered}."
                    )
                self.stdout.write(
                    self.style.SUCCESS(
                        f"verified={len(states)} customer_ids={len(customer_ids)}"
                    )
                )
                return
            if time.monotonic() >= deadline:
                counts = Counter(status for _job_id, status, _error_code in states)
                rendered = ",".join(
                    f"{status}:{count}" for status, count in sorted(counts.items())
                )
                raise CommandError(f"Timed out waiting for synchronization ({rendered}).")
            time.sleep(min(1, max(0, deadline - time.monotonic())))
