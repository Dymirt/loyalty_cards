"""Owner-only settings orchestration using provider registrations."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST

from dotykacka.models import AuditEvent
from tenants.authorization import can_manage_integrations
from tenants.authorization import superuser_required
from tenants.models import Tenant

from .contracts import SystemCheckResult
from .models import IntegrationConnection
from .registry import settings_providers, system_connection_checks


def _provider_map():
    return {spec.provider: spec for spec in settings_providers()}


def _connection_map(tenant):
    result = {}
    for spec in settings_providers():
        connection, _ = IntegrationConnection.objects.get_or_create(
            tenant=tenant, provider=spec.provider
        )
        result[spec.provider] = connection
    return result


def _panels(*, tenant, connections, bound_forms=None):
    bound_forms = bound_forms or {}
    panels = []
    for spec in settings_providers():
        connection = connections[spec.provider]
        form = bound_forms.get(spec.provider) or spec.form_class(
            tenant=tenant,
            connection=connection,
            prefix=spec.provider,
        )
        has_secret = bool(
            spec.secret_name
            and connection.has_secret(spec.secret_name)
        )
        is_dotykacka = spec.provider == IntegrationConnection.Provider.DOTYKACKA
        panels.append(
            {
                "spec": spec,
                "connection": connection,
                "form": form,
                "secret_configured": has_secret,
                "tester_available": spec.tester is not None and spec.tenant_testable,
                "dotykacka_connected": bool(
                    is_dotykacka
                    and has_secret
                    and connection.configuration.get("cloud_id")
                ),
                "dotykacka_cloud_id": (
                    connection.configuration.get("cloud_id") if is_dotykacka else ""
                ),
            }
        )
    return panels


@login_required
@require_http_methods(["GET", "POST"])
def integration_settings(request, tenant_slug):
    tenant = get_object_or_404(Tenant, slug=tenant_slug, is_active=True)
    if not can_manage_integrations(request.user, tenant):
        return HttpResponseForbidden("Nie masz uprawnień do konfiguracji tej firmy.")
    connections = _connection_map(tenant)
    bound_forms = {}
    if request.method == "POST":
        provider = request.POST.get("provider", "")
        spec = _provider_map().get(provider)
        if spec is None:
            return HttpResponseForbidden("Nieprawidłowy typ integracji.")
        form = spec.form_class(
            request.POST,
            tenant=tenant,
            connection=connections[provider],
            prefix=provider,
        )
        bound_forms[provider] = form
        if form.is_valid():
            connection = form.save()
            AuditEvent.objects.create(
                tenant=tenant,
                actor=request.user,
                action="integration.updated",
                object_type="IntegrationConnection",
                object_id=str(connection.pk),
                metadata={"provider": connection.provider, "enabled": connection.enabled},
            )
            messages.success(request, "Zapisano konfigurację integracji.")
            return redirect("integrations:settings", tenant_slug=tenant.slug)
    return render(
        request,
        "integrations/settings.html",
        {
            "tenant": tenant,
            "panels": _panels(
                tenant=tenant,
                connections=connections,
                bound_forms=bound_forms,
            ),
            "active_nav": "integrations",
            "can_manage_integrations": True,
        },
    )


@login_required
@require_POST
def test_integration(request, tenant_slug, provider):
    tenant = get_object_or_404(Tenant, slug=tenant_slug, is_active=True)
    if not can_manage_integrations(request.user, tenant):
        return HttpResponseForbidden("Nie masz uprawnień do konfiguracji tej firmy.")
    spec = _provider_map().get(provider)
    if spec is not None and not spec.tenant_testable:
        return HttpResponseForbidden(
            "To połączenie jest testowane przez operatora platformy."
        )
    connection = get_object_or_404(
        IntegrationConnection,
        tenant=tenant,
        provider=provider,
    )
    ok = False
    if spec is None or spec.tester is None:
        status_text = "Brak testu dla tej integracji."
    else:
        try:
            spec.tester(connection)
        except Exception as exc:
            connection.last_tested_at = timezone.now()
            connection.last_error_code = getattr(
                exc, "error_code", type(exc).__name__
            )[:80]
            connection.save(
                update_fields=("last_tested_at", "last_error_code", "updated_at")
            )
            status_text = "Test nie powiódł się. Sprawdź konfigurację."
        else:
            ok = True
            status_text = "Połączenie działa."
        AuditEvent.objects.create(
            tenant=tenant,
            actor=request.user,
            action="integration.tested",
            object_type="IntegrationConnection",
            object_id=str(connection.pk),
            metadata={"provider": provider, "succeeded": ok},
        )
    if request.headers.get("HX-Request") == "true":
        return render(
            request,
            "integrations/partials/status.html",
            {"connection": connection, "ok": ok, "status_text": status_text},
        )
    (messages.success if ok else messages.error)(request, status_text)
    return redirect("integrations:settings", tenant_slug=tenant.slug)


def _system_check_map():
    return {spec.key: spec for spec in system_connection_checks()}


def _run_system_check(spec):
    try:
        result = spec.checker()
    except Exception as exc:
        code = str(getattr(exc, "error_code", type(exc).__name__))[:80]
        return SystemCheckResult(
            ok=False,
            summary="Test nie powiódł się. Sprawdź konfigurację i logi serwera.",
            details=(f"Kod błędu: {code}",),
        )
    if not isinstance(result, SystemCheckResult):
        return SystemCheckResult(
            ok=False,
            summary="Test zwrócił nieprawidłowy wynik.",
        )
    return result


def _system_check_panels(results=None):
    results = results or {}
    return [
        {"spec": spec, "result": results.get(spec.key)}
        for spec in system_connection_checks()
    ]


def _system_connections_context(results=None):
    return {"checks": _system_check_panels(results)}


@superuser_required
@require_http_methods(["GET"])
def system_connections(request):
    return render(
        request,
        "integrations/system_connections.html",
        _system_connections_context(),
    )


@superuser_required
@require_POST
def test_system_connection(request, key):
    checks = _system_check_map()
    if key == "all":
        results = {
            check_key: _run_system_check(spec)
            for check_key, spec in checks.items()
        }
        return render(
            request,
            "integrations/system_connections.html",
            _system_connections_context(results),
        )
    spec = checks.get(key)
    if spec is None:
        return HttpResponseForbidden("Nieprawidłowy test połączenia systemowego.")
    return render(
        request,
        "integrations/partials/system_check_status.html",
        {"result": _run_system_check(spec)},
    )


__all__ = [
    "integration_settings",
    "system_connections",
    "test_integration",
    "test_system_connection",
]
