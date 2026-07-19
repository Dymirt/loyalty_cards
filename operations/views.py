"""Public redacted probes and superuser-only operations console."""

from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_GET, require_POST

from marketing.models import MarketingLead
from tenants.authorization import superuser_required

from .forms import AlertActionForm
from .health import collect_health_status
from .models import OperationalAlert
from .services import acknowledge_alert, resolve_alert


@require_GET
def liveness(request):
    response = JsonResponse({"status": "ok"})
    response["Cache-Control"] = "no-store"
    return response


@require_GET
def readiness(request):
    status = collect_health_status()
    response = JsonResponse(
        {"status": "ok" if status["ok"] else "degraded"},
        status=200 if status["ok"] else 503,
    )
    response["Cache-Control"] = "no-store"
    return response


@superuser_required
@require_GET
def dashboard(request):
    retention_cutoff = timezone.now() - timedelta(
        days=settings.MARKETING_LEAD_RETENTION_DAYS
    )
    return render(
        request,
        "operations/dashboard.html",
        {
            "health": collect_health_status(),
            "alerts": OperationalAlert.objects.select_related(
                "tenant", "acknowledged_by", "resolved_by"
            ).prefetch_related("events")[:100],
            "retention_due_count": MarketingLead.objects.filter(
                created_at__lt=retention_cutoff
            ).count(),
            "retention_cutoff": retention_cutoff,
        },
    )


def _alert_action(request, alert_id, *, action):
    alert = get_object_or_404(OperationalAlert, public_id=alert_id)
    form = AlertActionForm(request.POST)
    if not form.is_valid():
        messages.error(request, _("Podaj powód operacji."))
        return redirect("operations:dashboard")
    if action == "acknowledge":
        acknowledge_alert(
            alert=alert,
            actor=request.user,
            reason=form.cleaned_data["reason"],
        )
        messages.success(request, _("Alert został potwierdzony."))
    else:
        resolve_alert(
            alert=alert,
            actor=request.user,
            reason=form.cleaned_data["reason"],
        )
        messages.success(request, _("Alert został rozwiązany z zapisem historii."))
    return redirect("operations:dashboard")


@superuser_required
@require_POST
def acknowledge(request, alert_id):
    return _alert_action(request, alert_id, action="acknowledge")


@superuser_required
@require_POST
def resolve(request, alert_id):
    return _alert_action(request, alert_id, action="resolve")


__all__ = ["acknowledge", "dashboard", "liveness", "readiness", "resolve"]
