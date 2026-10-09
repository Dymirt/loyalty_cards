"""Tenant campaign composer and campaign-history views."""

import mimetypes
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import FileResponse, Http404, HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.decorators.http import require_GET, require_http_methods

from integrations.models import IntegrationConnection
from tenants.authorization import can_access_tenant, can_manage_integrations
from tenants.models import Tenant

from .campaigns import (
    add_campaign_assets,
    eligible_recipient_count,
    generate_campaign_content,
    schedule_campaign,
)
from .forms import EmailCampaignForm
from .models import CampaignAsset, EmailCampaign


def _tenant_for_campaigns(request, tenant_slug):
    tenant = get_object_or_404(
        Tenant.objects.select_related("brand"),
        slug=tenant_slug,
        is_active=True,
    )
    if not can_access_tenant(request.user, tenant):
        return tenant, HttpResponseForbidden(_("Nie masz dostępu do tej firmy."))
    return tenant, None


def _campaign_context(tenant, user, campaign=None, form=None):
    openai_connection = IntegrationConnection.objects.filter(
        tenant=tenant,
        provider="openai",
        enabled=True,
    ).first()
    return {
        "tenant": tenant,
        "campaign": campaign,
        "form": form or EmailCampaignForm(campaign=campaign),
        "assets": campaign.assets.all() if campaign else (),
        "eligible_recipient_count": eligible_recipient_count(tenant),
        "openai_ready": bool(
            openai_connection and openai_connection.has_secret("api_key")
        ),
        "active_nav": "communications",
        "can_manage_integrations": can_manage_integrations(user, tenant),
        "can_manage_card_designs": can_manage_integrations(user, tenant),
        "can_manage_billing": can_manage_integrations(user, tenant),
        "can_manage_printing": can_manage_integrations(user, tenant),
    }


@login_required
@require_GET
def campaign_list(request, tenant_slug):
    tenant, denied = _tenant_for_campaigns(request, tenant_slug)
    if denied:
        return denied
    campaigns = EmailCampaign.objects.filter(tenant=tenant).select_related("created_by")
    scheduled = campaigns.filter(
        status__in=(
            EmailCampaign.Status.SCHEDULED,
            EmailCampaign.Status.SENDING,
        )
    ).order_by("scheduled_for", "pk")
    history = campaigns.exclude(
        status__in=(
            EmailCampaign.Status.SCHEDULED,
            EmailCampaign.Status.SENDING,
        )
    )
    return render(
        request,
        "communications/campaign_list.html",
        {
            **_campaign_context(tenant, request.user),
            "scheduled_campaigns": scheduled,
            "campaign_history": history,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def campaign_compose(request, tenant_slug, campaign_id=None):
    tenant, denied = _tenant_for_campaigns(request, tenant_slug)
    if denied:
        return denied
    campaign = None
    if campaign_id is not None:
        campaign = get_object_or_404(EmailCampaign, tenant=tenant, pk=campaign_id)
    if request.method == "GET":
        return render(
            request,
            "communications/campaign_compose.html",
            _campaign_context(tenant, request.user, campaign),
        )
    if campaign is not None and not campaign.is_editable:
        return HttpResponseForbidden(_("Zaplanowanej kampanii nie można już edytować."))
    action = request.POST.get("action", "save")
    if action not in {"save", "generate", "schedule"}:
        return HttpResponse(status=400)
    try:
        tenant_timezone = ZoneInfo(tenant.timezone)
    except ZoneInfoNotFoundError:
        tenant_timezone = ZoneInfo("Europe/Warsaw")
    with timezone.override(tenant_timezone):
        form = EmailCampaignForm(
            request.POST,
            request.FILES,
            campaign=campaign,
            action=action,
        )
        valid = form.is_valid()
    if not valid:
        return render(
            request,
            "communications/campaign_compose.html",
            _campaign_context(tenant, request.user, campaign, form),
            status=400,
        )
    previous_goal = campaign.goal if campaign else ""
    previous_links = campaign.reference_links if campaign else []
    if campaign is None:
        campaign = EmailCampaign(
            tenant=tenant,
            created_by=request.user,
            name=form.cleaned_data["goal"][:160],
            goal=form.cleaned_data["goal"],
            reference_links=form.cleaned_data["links"],
        )
    else:
        campaign.goal = form.cleaned_data["goal"]
        campaign.reference_links = form.cleaned_data["links"]
    uploads = form.cleaned_data.get("images") or []
    content_changed = bool(
        previous_goal != campaign.goal
        or previous_links != campaign.reference_links
        or uploads
    )
    if action == "save" and content_changed:
        campaign.subject = ""
        campaign.preheader = ""
        campaign.html_content = ""
        campaign.text_content = ""
        campaign.content_snapshot = {}
        campaign.ai_model = ""
        campaign.generation_source = EmailCampaign.GenerationSource.LOCAL
    campaign.name = campaign.name or campaign.goal[:160]
    campaign.full_clean()
    campaign.save()
    add_campaign_assets(campaign=campaign, uploads=uploads, actor=request.user)
    if action in {"generate", "schedule"}:
        campaign, fallback_error = generate_campaign_content(campaign)
        if fallback_error:
            messages.warning(
                request,
                _("Nie udało się użyć OpenAI. Utworzono bezpieczny szkic bazowy; sprawdź integrację i spróbuj ponownie."),
            )
        else:
            messages.success(request, _("Wygenerowano nowy szkic wiadomości."))
    if action == "schedule":
        try:
            campaign = schedule_campaign(
                campaign=campaign,
                scheduled_for=form.cleaned_data["scheduled_for"],
            )
        except ValidationError as exc:
            form.add_error(None, exc)
            return render(
                request,
                "communications/campaign_compose.html",
                _campaign_context(tenant, request.user, campaign, form),
                status=400,
            )
        messages.success(
            request,
            _("Zaplanowano wysyłkę do %(count)s odbiorców.")
            % {"count": campaign.recipient_count},
        )
        return redirect("communications:list", tenant_slug=tenant.slug)
    if action == "save":
        messages.success(request, _("Szkic został zapisany."))
    return redirect(
        "communications:edit",
        tenant_slug=tenant.slug,
        campaign_id=campaign.pk,
    )


@login_required
@require_GET
@xframe_options_sameorigin
def campaign_preview(request, tenant_slug, campaign_id):
    tenant, denied = _tenant_for_campaigns(request, tenant_slug)
    if denied:
        return denied
    campaign = get_object_or_404(EmailCampaign, tenant=tenant, pk=campaign_id)
    if not campaign.html_content:
        content = (
            "<!doctype html><html lang='pl'><body style='font-family:Arial,sans-serif;"
            "padding:48px;background:#f5f2eb;color:#48433b;text-align:center'>"
            "<h1 style='color:#191713'>Podgląd pojawi się tutaj</h1>"
            "<p>Uzupełnij cel komunikacji i wybierz „Generuj z AI”.</p></body></html>"
        )
    else:
        content = campaign.html_content
        for index, asset in enumerate(campaign.assets.all()[:3], start=1):
            path = reverse(
                "communications:asset",
                kwargs={
                    "tenant_slug": tenant.slug,
                    "campaign_id": campaign.pk,
                    "asset_id": asset.pk,
                },
            )
            content = content.replace(f"cid:campaign-image-{index}", path)
        content = content.replace("{{ first_name }}", "Marto")
    response = HttpResponse(content, content_type="text/html; charset=utf-8")
    response["Content-Security-Policy"] = (
        "default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'; "
        "base-uri 'none'; form-action 'none'; frame-ancestors 'self'"
    )
    response["Cache-Control"] = "private, no-store"
    return response


@login_required
@require_GET
def campaign_asset(request, tenant_slug, campaign_id, asset_id):
    tenant, denied = _tenant_for_campaigns(request, tenant_slug)
    if denied:
        return denied
    asset = get_object_or_404(
        CampaignAsset,
        tenant=tenant,
        campaign_id=campaign_id,
        pk=asset_id,
    )
    try:
        asset.image.open("rb")
    except OSError as exc:
        raise Http404(_("Plik materiału nie istnieje.")) from exc
    content_type = asset.content_type or mimetypes.guess_type(asset.original_name)[0]
    response = FileResponse(asset.image, content_type=content_type or "image/jpeg")
    response["Cache-Control"] = "private, max-age=3600"
    response["X-Content-Type-Options"] = "nosniff"
    return response


__all__ = [
    "campaign_asset",
    "campaign_compose",
    "campaign_list",
    "campaign_preview",
]
