"""Tenant card artwork HTTP adapters."""

import mimetypes

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import FileResponse, Http404, HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from tenants.authorization import can_manage_card_designs
from tenants.forms import TenantBrandForm
from tenants.models import Tenant

from .forms import CardDesignForm
from .models import CardArtifact, CardDesign
from .services import (
    apply_brand_defaults,
    brand_snapshot_values,
    build_sample_sheet,
    design_snapshot_values,
    publish_design_release,
    render_card,
    resolve_artifact_path,
    spec_from_values,
)


def _card_design_context(tenant, brand_form, design_form, proof=None, sample_sheet=None):
    designs = CardDesign.objects.filter(tenant=tenant).select_related("brand_revision")
    current_design = designs.first()
    proof_artifacts = (
        CardArtifact.objects.filter(
            tenant=tenant,
            design=current_design,
            kind__in=(
                CardArtifact.Kind.PROOF_FRONT,
                CardArtifact.Kind.PROOF_BACK,
                CardArtifact.Kind.MANIFEST,
            ),
        )[:12]
        if current_design
        else []
    )
    return {
        "tenant": tenant,
        "brand_form": brand_form,
        "design_form": design_form,
        "designs": designs,
        "current_design": current_design,
        "proof": proof,
        "sample_sheet": sample_sheet or [],
        "proof_artifacts": proof_artifacts,
        "active_nav": "card_design",
        "can_manage_integrations": True,
        "can_manage_card_designs": True,
    }


@login_required
@require_http_methods(["GET", "POST"])
def card_design_settings(request, tenant_slug):
    tenant = get_object_or_404(
        Tenant.objects.select_related("brand"),
        slug=tenant_slug,
        is_active=True,
    )
    if not can_manage_card_designs(request.user, tenant):
        return HttpResponseForbidden("Nie masz uprawnień do projektu kart tej firmy.")
    current_design = CardDesign.objects.filter(tenant=tenant).first()
    if request.method == "GET":
        return render(
            request,
            "card_artwork/settings.html",
            _card_design_context(
                tenant,
                TenantBrandForm(instance=tenant.brand, prefix="brand"),
                CardDesignForm(tenant=tenant, current_design=current_design, prefix="design"),
            ),
        )
    brand_form = TenantBrandForm(request.POST, instance=tenant.brand, prefix="brand")
    design_form = CardDesignForm(
        request.POST,
        request.FILES,
        tenant=tenant,
        current_design=current_design,
        prefix="design",
    )
    proof = None
    sample_sheet = []
    status = 400
    if brand_form.is_valid() and design_form.is_valid():
        brand_values = brand_snapshot_values(brand_form.cleaned_data)
        design_values = apply_brand_defaults(
            brand_values,
            design_snapshot_values(design_form.cleaned_data),
        )
        try:
            spec = spec_from_values(
                tenant=tenant,
                values=design_values,
                background_upload=design_form.cleaned_data.get("background_image"),
                logo_upload=design_form.cleaned_data.get("logo_image"),
                fallback_design=current_design,
            )
            rendered = render_card(spec, f"{tenant.card_prefix}-1")
            proof = {
                **rendered.data_urls(),
                "checksum": spec.checksum,
                "crop_box": rendered.crop_box,
                "crop_plan": rendered.crop_plan.metadata(),
                "width_px": rendered.width_px,
                "height_px": rendered.height_px,
                "dpi": rendered.dpi,
            }
            sample_sheet = build_sample_sheet(
                spec,
                count=design_form.cleaned_data.get("sample_count") or 6,
            )
            status = 200
            if request.POST.get("action") == "publish":
                design = publish_design_release(
                    tenant=tenant,
                    actor=request.user,
                    brand_values=brand_values,
                    design_values=design_values,
                    background_upload=design_form.cleaned_data.get("background_image"),
                    logo_upload=design_form.cleaned_data.get("logo_image"),
                )
                messages.success(request, f"Opublikowano projekt karty v{design.version}.")
                target = reverse(
                    "dotykacka:card_design_settings",
                    kwargs={"tenant_slug": tenant.slug},
                )
                if request.headers.get("HX-Request") == "true":
                    response = HttpResponse(status=204)
                    response["HX-Redirect"] = target
                    return response
                return redirect(target)
        except ValidationError as exc:
            design_form.add_error(None, exc)
            status = 400
    context = _card_design_context(
        tenant,
        brand_form,
        design_form,
        proof,
        sample_sheet,
    )
    if request.headers.get("HX-Request") == "true":
        return render(
            request,
            "card_artwork/partials/proof.html",
            context,
            status=status,
        )
    return render(request, "card_artwork/settings.html", context, status=status)


@login_required
def card_artifact_download(request, tenant_slug, artifact_id):
    tenant = get_object_or_404(Tenant, slug=tenant_slug, is_active=True)
    if not can_manage_card_designs(request.user, tenant):
        return HttpResponseForbidden("Nie masz dostępu do plików tej firmy.")
    artifact = get_object_or_404(CardArtifact, pk=artifact_id, tenant=tenant)
    path = resolve_artifact_path(artifact)
    if not path.is_file():
        raise Http404("Plik artefaktu nie istnieje.")
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return FileResponse(
        path.open("rb"),
        as_attachment=True,
        filename=path.name,
        content_type=content_type,
    )
