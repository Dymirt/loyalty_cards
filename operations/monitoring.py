"""Deterministic, database-only SaaS operational monitoring rules."""

from datetime import timedelta

from django.conf import settings
from django.db.models import Count, Sum
from django.utils import timezone
from django.utils.translation import gettext as _

from billing.models import BillingPeriod, CardPack, TenantSubscription, UsageEvent
from cards.models import PhysicalCard
from dotykacka.models import Tenant, TenantMembership
from integrations.models import IntegrationJob
from printing.models import PrintJob, PrintRequest

from .models import OperationalAlert, WorkerHeartbeat
from .services import (
    detect_operational_alert,
    resolve_absent_monitor_alerts,
    worker_health,
)


MANAGED_CATEGORIES = {
    "entitlement",
    "integration_job",
    "inventory",
    "pack_balance",
    "print_job",
    "provider_auth",
    "worker",
}
AUTH_ERROR_CODES = {
    "401",
    "auth_failed",
    "authentication_failed",
    "brevo_unauthorized",
    "configuration_required",
    "unauthorized",
}


def _detect(active, **kwargs):
    fingerprint = kwargs["fingerprint"]
    detect_operational_alert(**kwargs)
    active.add(fingerprint)


def scan_operational_alerts(*, now=None):
    now = now or timezone.now()
    active = set()

    for job in IntegrationJob.objects.select_related("tenant").filter(
        status=IntegrationJob.Status.FAILED
    ):
        _detect(
            active,
            fingerprint=f"integration-job:{job.pk}",
            category="integration_job",
            severity=OperationalAlert.Severity.CRITICAL,
            tenant=job.tenant,
            title=_("Zadanie integracji zakończone błędem"),
            safe_summary=_("Zadanie %(kind)s wymaga kontroli operatora.")
            % {"kind": job.kind},
            source_type="IntegrationJob",
            source_id=job.pk,
            safe_snapshot={"kind": job.kind, "error_code": job.last_error_code},
            now=now,
        )

    for job in PrintJob.objects.select_related("print_run__tenant").filter(
        status=PrintJob.Status.FAILED
    ):
        _detect(
            active,
            fingerprint=f"print-job:{job.pk}",
            category="print_job",
            severity=OperationalAlert.Severity.CRITICAL,
            tenant=job.print_run.tenant,
            title=_("Generowanie pakietu druku nie powiodło się"),
            safe_summary=_("Pakiet produkcyjny wymaga kontroli i bezpiecznego ponowienia."),
            source_type="PrintJob",
            source_id=job.pk,
            safe_snapshot={"error_code": job.last_error_code},
            now=now,
        )

    failed_requests = PrintRequest.objects.select_related("tenant").filter(
        status=PrintRequest.Status.FAILED
    )
    for print_request in failed_requests:
        _detect(
            active,
            fingerprint=f"print-request:{print_request.pk}",
            category="print_job",
            severity=OperationalAlert.Severity.CRITICAL,
            tenant=print_request.tenant,
            title=_("Zamówienie druku ma status błędu"),
            safe_summary=_("Zamówienie wymaga kontroli operatora przed kolejną operacją."),
            source_type="PrintRequest",
            source_id=print_request.pk,
            now=now,
        )

    inventory_rows = PhysicalCard.objects.filter(
        tenant__is_active=True,
        status=PhysicalCard.Status.AVAILABLE,
    ).values("tenant_id").annotate(available=Count("pk"))
    inventory_by_tenant = {row["tenant_id"]: row["available"] for row in inventory_rows}
    for tenant in Tenant.objects.filter(is_active=True):
        available = inventory_by_tenant.get(tenant.pk, 0)
        if available <= settings.MONITOR_LOW_INVENTORY_THRESHOLD:
            _detect(
                active,
                fingerprint=f"inventory-low:{tenant.pk}",
                category="inventory",
                severity=OperationalAlert.Severity.WARNING,
                tenant=tenant,
                title=_("Niski zapas nieprzypisanych kart"),
                safe_summary=_("Pozostało %(count)s dostępnych kart.")
                % {"count": available},
                source_type="Tenant",
                source_id=tenant.pk,
                safe_snapshot={"available": available},
                now=now,
            )

    for pack in CardPack.objects.select_related("tenant").filter(is_active=True):
        remaining = pack.purchased_quantity - pack.consumed_quantity
        threshold = max(10, int(pack.purchased_quantity * 0.1))
        if remaining <= threshold:
            _detect(
                active,
                fingerprint=f"pack-low:{pack.pk}",
                category="pack_balance",
                severity=OperationalAlert.Severity.WARNING,
                tenant=pack.tenant,
                title=_("Niski stan pakietu kart"),
                safe_summary=_("W pakiecie pozostało %(remaining)s z %(total)s kart.")
                % {"remaining": remaining, "total": pack.purchased_quantity},
                source_type="CardPack",
                source_id=pack.pk,
                safe_snapshot={"remaining": remaining, "purchased": pack.purchased_quantity},
                now=now,
            )

    active_subscriptions = TenantSubscription.objects.select_related(
        "tenant", "plan_version__entitlement_policy"
    ).filter(status=TenantSubscription.Status.ACTIVE)
    warning_percent = settings.MONITOR_ENTITLEMENT_WARNING_PERCENT
    for subscription in active_subscriptions:
        policy = getattr(subscription.plan_version, "entitlement_policy", None)
        if policy is None:
            continue
        period = BillingPeriod.objects.filter(
            subscription=subscription,
            status=BillingPeriod.Status.OPEN,
            starts_at__lte=now,
            ends_at__gt=now,
        ).first()
        if period and policy.card_issuance_limit:
            issued = (
                UsageEvent.objects.filter(
                    billing_period=period,
                    kind__in=(
                        UsageEvent.Kind.PHYSICAL_CARD_ISSUED,
                        UsageEvent.Kind.VIRTUAL_CARD_ISSUED,
                    ),
                ).aggregate(total=Sum("quantity"))["total"]
                or 0
            )
            percent = int(issued * 100 / policy.card_issuance_limit)
            if percent >= warning_percent:
                _detect(
                    active,
                    fingerprint=f"entitlement-issuance:{period.pk}",
                    category="entitlement",
                    severity=OperationalAlert.Severity.WARNING,
                    tenant=subscription.tenant,
                    title=_("Limit wydań kart zbliża się do końca"),
                    safe_summary=_("Wykorzystano %(used)s z %(limit)s wydań.")
                    % {"used": issued, "limit": policy.card_issuance_limit},
                    source_type="BillingPeriod",
                    source_id=period.pk,
                    safe_snapshot={"used": issued, "limit": policy.card_issuance_limit},
                    now=now,
                )
        if policy.active_seat_limit:
            seats = TenantMembership.objects.filter(
                tenant=subscription.tenant,
                is_active=True,
            ).count()
            percent = int(seats * 100 / policy.active_seat_limit)
            if percent >= warning_percent:
                _detect(
                    active,
                    fingerprint=f"entitlement-seats:{subscription.pk}",
                    category="entitlement",
                    severity=OperationalAlert.Severity.WARNING,
                    tenant=subscription.tenant,
                    title=_("Limit użytkowników zbliża się do końca"),
                    safe_summary=_("Aktywnych jest %(used)s z %(limit)s użytkowników.")
                    % {"used": seats, "limit": policy.active_seat_limit},
                    source_type="TenantSubscription",
                    source_id=subscription.pk,
                    safe_snapshot={"used": seats, "limit": policy.active_seat_limit},
                    now=now,
                )

    auth_cutoff = now - timedelta(hours=24)
    auth_failures = (
        IntegrationJob.objects.filter(
            status=IntegrationJob.Status.FAILED,
            connection__isnull=False,
            last_error_code__in=AUTH_ERROR_CODES,
            updated_at__gte=auth_cutoff,
        )
        .values("connection_id", "tenant_id", "connection__provider")
        .annotate(failures=Count("pk"))
    )
    tenant_map = {
        tenant.pk: tenant
        for tenant in Tenant.objects.filter(pk__in=[row["tenant_id"] for row in auth_failures])
    }
    for row in auth_failures:
        if row["failures"] < settings.MONITOR_PROVIDER_AUTH_FAILURE_THRESHOLD:
            continue
        tenant = tenant_map[row["tenant_id"]]
        _detect(
            active,
            fingerprint=f"provider-auth:{row['connection_id']}",
            category="provider_auth",
            severity=OperationalAlert.Severity.CRITICAL,
            tenant=tenant,
            title=_("Powtarzające się błędy autoryzacji integracji"),
            safe_summary=(
                _("Integracja %(provider)s zgłosiła %(count)s błędy autoryzacji w ciągu 24 godzin.")
                % {
                    "provider": row["connection__provider"],
                    "count": row["failures"],
                }
            ),
            source_type="IntegrationConnection",
            source_id=row["connection_id"],
            safe_snapshot={"failures": row["failures"], "provider": row["connection__provider"]},
            now=now,
        )

    for worker_type in (
        WorkerHeartbeat.WorkerType.INTEGRATION,
        WorkerHeartbeat.WorkerType.PRINTING,
    ):
        status = worker_health(
            worker_type=worker_type,
            max_age_seconds=settings.WORKER_HEARTBEAT_MAX_AGE_SECONDS,
            now=now,
        )
        if not status["ok"]:
            _detect(
                active,
                fingerprint=f"worker-stale:{worker_type}",
                category="worker",
                severity=OperationalAlert.Severity.CRITICAL,
                title=_("Brak aktualnego sygnału procesu roboczego"),
                safe_summary=_("Proces %(worker)s nie zgłosił aktualnego sygnału.")
                % {"worker": worker_type},
                source_type="WorkerHeartbeat",
                source_id=worker_type,
                safe_snapshot={"age_seconds": status.get("age_seconds")},
                now=now,
            )

    resolved = resolve_absent_monitor_alerts(
        managed_categories=MANAGED_CATEGORIES,
        active_fingerprints=active,
        now=now,
    )
    return {"active": len(active), "resolved": resolved}


__all__ = ["MANAGED_CATEGORIES", "scan_operational_alerts"]
