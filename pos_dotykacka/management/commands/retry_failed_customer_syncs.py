"""Safely preview or requeue failed Dotykačka customer synchronizations."""

from django.core.management.base import BaseCommand

from integrations.models import IntegrationJob
from integrations.services import retry_failed_job
from pos_dotykacka.jobs import CUSTOMER_UPSERT_JOB


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

    def handle(self, *args, **options):
        error_codes = options["error_code"] or ["HTTPError"]
        jobs = IntegrationJob.objects.filter(
            kind=CUSTOMER_UPSERT_JOB,
            status=IntegrationJob.Status.FAILED,
            last_error_code__in=error_codes,
        ).order_by("pk")
        if options["job_id"]:
            jobs = jobs.filter(pk__in=options["job_id"])
        job_ids = list(jobs.values_list("pk", flat=True))
        rendered_ids = ",".join(str(job_id) for job_id in job_ids) or "none"
        self.stdout.write(f"matched={len(job_ids)} job_ids={rendered_ids}")
        if not options["apply"]:
            self.stdout.write("dry-run: pass --apply to requeue these jobs")
            return
        for job in jobs:
            retry_failed_job(job=job)
        self.stdout.write(self.style.SUCCESS(f"requeued={len(job_ids)}"))
