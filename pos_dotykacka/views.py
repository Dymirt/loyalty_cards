"""Owner-bound browser endpoints for Dotykačka Connector v2."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from dotykacka.models import AuditEvent
from integrations.contracts import IntegrationConfigurationError
from tenants.authorization import can_manage_integrations
from tenants.models import Tenant

from .services import begin_connection, complete_connection, disconnect_connection


@login_required
@require_POST
def connect_dotykacka(request, tenant_slug):
    tenant = get_object_or_404(Tenant, slug=tenant_slug, is_active=True)
    if not can_manage_integrations(request.user, tenant):
        return HttpResponseForbidden(
            "Nie masz uprawnień do połączenia tej firmy z Dotykačka."
        )
    if not request.session.session_key:
        request.session.create()
    redirect_uri = request.build_absolute_uri(reverse("pos_dotykacka:callback"))
    try:
        endpoint, payload = begin_connection(
            tenant=tenant,
            user=request.user,
            session_key=request.session.session_key,
            redirect_uri=redirect_uri,
        )
    except IntegrationConfigurationError:
        messages.error(
            request,
            "Brakuje konfiguracji platformowej aplikacji Dotykačka Connector.",
        )
        return redirect("integrations:settings", tenant_slug=tenant.slug)
    request.session["dotykacka_connect_tenant_slug"] = tenant.slug
    return render(
        request,
        "pos_dotykacka/connect_authorize.html",
        {"tenant": tenant, "connector_endpoint": endpoint, "payload": payload},
    )


@login_required
@require_GET
def dotykacka_callback(request):
    tenant_slug = request.session.get("dotykacka_connect_tenant_slug", "")
    try:
        connection = complete_connection(
            state=request.GET.get("state", ""),
            refresh_token=request.GET.get("token", ""),
            cloud_id=request.GET.get("cloudid", ""),
            user=request.user,
            session_key=request.session.session_key or "",
        )
    except Exception as exc:
        if getattr(exc, "error_code", "") == "cloud_change_requires_disconnect":
            error_message = (
                "Wybrano inną chmurę. Najpierw rozłącz obecne połączenie Dotykačka."
            )
        else:
            error_message = (
                "Nie udało się połączyć Dotykačka. Rozpocznij połączenie ponownie."
            )
        messages.error(
            request,
            error_message,
        )
        if tenant_slug:
            return redirect("integrations:settings", tenant_slug=tenant_slug)
        return redirect("index")
    request.session.pop("dotykacka_connect_tenant_slug", None)
    AuditEvent.objects.create(
        tenant=connection.tenant,
        actor=request.user,
        action="integration.connected",
        object_type="IntegrationConnection",
        object_id=str(connection.pk),
        metadata={"provider": connection.provider},
    )
    messages.success(request, "Połączono chmurę Dotykačka. Uzupełnij grupę rabatową.")
    return redirect("integrations:settings", tenant_slug=connection.tenant.slug)


@login_required
@require_POST
def disconnect_dotykacka(request, tenant_slug):
    tenant = get_object_or_404(Tenant, slug=tenant_slug, is_active=True)
    if not can_manage_integrations(request.user, tenant):
        return HttpResponseForbidden(
            "Nie masz uprawnień do rozłączenia tej firmy z Dotykačka."
        )
    try:
        connection, previous_cloud_id = disconnect_connection(tenant=tenant)
    except IntegrationConfigurationError:
        messages.error(request, "Połączenie Dotykačka nie jest skonfigurowane.")
    else:
        request.session.pop("dotykacka_connect_tenant_slug", None)
        AuditEvent.objects.create(
            tenant=tenant,
            actor=request.user,
            action="integration.disconnected",
            object_type="IntegrationConnection",
            object_id=str(connection.pk),
            metadata={
                "provider": connection.provider,
                "cloud_id": previous_cloud_id,
            },
        )
        messages.success(request, "Rozłączono Dotykačka dla tej firmy.")
    return redirect("integrations:settings", tenant_slug=tenant.slug)


__all__ = [
    "connect_dotykacka",
    "disconnect_dotykacka",
    "dotykacka_callback",
]
