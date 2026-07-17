"""Transactional enqueue, claim and completion operations for provider jobs."""

from datetime import timedelta

from django.db import connection as database_connection
from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from .contracts import RetryableIntegrationError
from .models import IntegrationJob


SAFE_PAYLOAD_KEYS = frozenset({"customer_id", "wallet_id", "connection_id", "reason"})


def _safe_payload(payload):
    unexpected = set(payload) - SAFE_PAYLOAD_KEYS
    if unexpected:
        raise ValueError("Integration jobs may contain identifiers only.")
    return dict(payload)


def enqueue_job(*, tenant, kind, idempotency_key, payload, connection=None, max_attempts=5):
    job, _ = IntegrationJob.objects.get_or_create(
        tenant=tenant,
        idempotency_key=idempotency_key,
        defaults={
            "connection": connection,
            "kind": kind,
            "payload": _safe_payload(payload),
            "max_attempts": max_attempts,
        },
    )
    return job


@transaction.atomic
def claim_next_job(*, worker_id, kinds=(), stale_after=timedelta(minutes=5)):
    now = timezone.now()
    stale_before = now - stale_after
    IntegrationJob.objects.filter(
        status=IntegrationJob.Status.RUNNING,
        locked_at__lt=stale_before,
        attempts__gte=F("max_attempts"),
    ).update(
        status=IntegrationJob.Status.FAILED,
        finished_at=now,
        locked_at=None,
        locked_by="",
        last_error_code="worker_lost_after_final_attempt",
        updated_at=now,
    )
    eligible = Q(status__in=(IntegrationJob.Status.PENDING, IntegrationJob.Status.RETRY)) | Q(
        status=IntegrationJob.Status.RUNNING,
        locked_at__lt=stale_before,
    )
    queryset = IntegrationJob.objects.filter(
        eligible,
        available_at__lte=now,
        attempts__lt=F("max_attempts"),
    )
    if kinds:
        queryset = queryset.filter(kind__in=kinds)
    if database_connection.features.has_select_for_update:
        queryset = queryset.select_for_update(
            skip_locked=database_connection.features.has_select_for_update_skip_locked
        )
    job = queryset.order_by("available_at", "created_at", "pk").first()
    if job is None:
        return None
    job.status = IntegrationJob.Status.RUNNING
    job.attempts += 1
    job.locked_at = now
    job.locked_by = worker_id
    job.last_error_code = ""
    job.save(
        update_fields=(
            "status",
            "attempts",
            "locked_at",
            "locked_by",
            "last_error_code",
            "updated_at",
        )
    )
    return job


def complete_job(job):
    now = timezone.now()
    IntegrationJob.objects.filter(pk=job.pk, status=IntegrationJob.Status.RUNNING).update(
        status=IntegrationJob.Status.SUCCEEDED,
        finished_at=now,
        locked_at=None,
        locked_by="",
        last_error_code="",
        updated_at=now,
    )


def fail_job(job, exc):
    now = timezone.now()
    error_code = getattr(exc, "error_code", type(exc).__name__)[:80]
    retryable = isinstance(exc, RetryableIntegrationError)
    if retryable and job.attempts < job.max_attempts:
        retry_after = exc.retry_after
        delay = max(1, min(int(retry_after or 2 ** job.attempts), 3600))
        status = IntegrationJob.Status.RETRY
        available_at = now + timedelta(seconds=delay)
        finished_at = None
    else:
        status = IntegrationJob.Status.FAILED
        available_at = job.available_at
        finished_at = now
    IntegrationJob.objects.filter(pk=job.pk, status=IntegrationJob.Status.RUNNING).update(
        status=status,
        available_at=available_at,
        finished_at=finished_at,
        locked_at=None,
        locked_by="",
        last_error_code=error_code,
        updated_at=now,
    )


__all__ = ["claim_next_job", "complete_job", "enqueue_job", "fail_job"]
