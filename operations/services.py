"""Application services for worker health and audited operational alerts."""

from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import DatabaseError, transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from .models import OperationalAlert, OperationalAlertEvent, WorkerHeartbeat


def _safe_metadata(value):
    result = {}
    for key, item in (value or {}).items():
        safe_key = str(key)[:80]
        if any(marker in safe_key.lower() for marker in ("secret", "password", "token", "authorization", "api_key")):
            continue
        if isinstance(item, (bool, int, float)) or item is None:
            result[safe_key] = item
        else:
            result[safe_key] = str(item)[:240]
    return result


def record_worker_heartbeat(
    *, worker_type, worker_id, processed_count=0, status="running", safe_metadata=None
):
    now = timezone.now()
    heartbeat, _created = WorkerHeartbeat.objects.update_or_create(
        worker_type=worker_type,
        worker_id=worker_id,
        defaults={
            "last_seen_at": now,
            "processed_count": max(0, int(processed_count)),
            "status": str(status)[:32],
            "safe_metadata": _safe_metadata(safe_metadata),
        },
    )
    return heartbeat


def safe_record_worker_heartbeat(**kwargs):
    try:
        return record_worker_heartbeat(**kwargs)
    except DatabaseError:
        # During a rolling deploy the additive heartbeat table may not exist for
        # a few seconds. Job processing continues and the next poll retries it.
        return None


def worker_health(*, worker_type, max_age_seconds, now=None):
    now = now or timezone.now()
    latest = (
        WorkerHeartbeat.objects.filter(worker_type=worker_type)
        .order_by("-last_seen_at", "-pk")
        .first()
    )
    if latest is None:
        return {"ok": False, "worker_type": worker_type, "age_seconds": None}
    age = max(0, int((now - latest.last_seen_at).total_seconds()))
    return {
        "ok": age <= max_age_seconds and latest.status == "running",
        "worker_type": worker_type,
        "age_seconds": age,
        "last_seen_at": latest.last_seen_at,
        "processed_count": latest.processed_count,
        "status": latest.status,
    }


@transaction.atomic
def detect_operational_alert(
    *,
    fingerprint,
    category,
    severity,
    title,
    safe_summary,
    tenant=None,
    source_type="",
    source_id="",
    safe_snapshot=None,
    now=None,
):
    now = now or timezone.now()
    alert = (
        OperationalAlert.objects.select_for_update()
        .filter(fingerprint=fingerprint)
        .first()
    )
    if alert is None:
        alert = OperationalAlert.objects.create(
            fingerprint=fingerprint,
            category=category,
            severity=severity,
            tenant=tenant,
            title=title[:180],
            safe_summary=safe_summary[:1000],
            source_type=source_type[:80],
            source_id=str(source_id)[:120],
            first_seen_at=now,
            last_seen_at=now,
        )
        OperationalAlertEvent.objects.create(
            alert=alert,
            kind=OperationalAlertEvent.Kind.DETECTED,
            safe_snapshot=_safe_metadata(safe_snapshot),
        )
        return alert, True
    was_resolved = alert.status == OperationalAlert.Status.RESOLVED
    alert.category = category
    alert.severity = severity
    alert.tenant = tenant
    alert.title = title[:180]
    alert.safe_summary = safe_summary[:1000]
    alert.source_type = source_type[:80]
    alert.source_id = str(source_id)[:120]
    alert.last_seen_at = now
    alert.occurrences += 1
    if was_resolved:
        alert.status = OperationalAlert.Status.OPEN
        alert.resolved_at = None
        alert.resolved_by = None
    alert.save()
    if was_resolved:
        OperationalAlertEvent.objects.create(
            alert=alert,
            kind=OperationalAlertEvent.Kind.REOPENED,
            safe_snapshot=_safe_metadata(safe_snapshot),
        )
    return alert, False


@transaction.atomic
def acknowledge_alert(*, alert, actor, reason):
    locked = OperationalAlert.objects.select_for_update().get(pk=alert.pk)
    if locked.status == OperationalAlert.Status.RESOLVED:
        raise ValidationError(_("Rozwiązanego alertu nie można potwierdzić."))
    locked.status = OperationalAlert.Status.ACKNOWLEDGED
    locked.acknowledged_at = timezone.now()
    locked.acknowledged_by = actor
    locked.save()
    OperationalAlertEvent.objects.create(
        alert=locked,
        kind=OperationalAlertEvent.Kind.ACKNOWLEDGED,
        actor=actor,
        reason=reason[:1000],
    )
    return locked


@transaction.atomic
def resolve_alert(*, alert, actor=None, reason=""):
    locked = OperationalAlert.objects.select_for_update().get(pk=alert.pk)
    if locked.status == OperationalAlert.Status.RESOLVED:
        return locked
    locked.status = OperationalAlert.Status.RESOLVED
    locked.resolved_at = timezone.now()
    locked.resolved_by = actor
    locked.save()
    OperationalAlertEvent.objects.create(
        alert=locked,
        kind=OperationalAlertEvent.Kind.RESOLVED,
        actor=actor,
        reason=reason[:1000],
    )
    return locked


def resolve_absent_monitor_alerts(*, managed_categories, active_fingerprints, now=None):
    now = now or timezone.now()
    cutoff = now - timedelta(seconds=1)
    alerts = OperationalAlert.objects.filter(
        category__in=managed_categories,
        status__in=(OperationalAlert.Status.OPEN, OperationalAlert.Status.ACKNOWLEDGED),
        last_seen_at__lt=cutoff,
    ).exclude(fingerprint__in=active_fingerprints)
    resolved = 0
    for alert in alerts.iterator():
        resolve_alert(alert=alert, reason="Warunek monitorowany przestał występować.")
        resolved += 1
    return resolved


__all__ = [
    "acknowledge_alert",
    "detect_operational_alert",
    "record_worker_heartbeat",
    "resolve_absent_monitor_alerts",
    "resolve_alert",
    "safe_record_worker_heartbeat",
    "worker_health",
]
