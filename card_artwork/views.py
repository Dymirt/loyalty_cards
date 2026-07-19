"""Tenant card artwork HTTP adapters."""

import mimetypes
from io import BytesIO

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import FileResponse, Http404, HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.http import require_http_methods
from PIL import Image, ImageOps

from tenants.authorization import can_manage_card_designs
from tenants.forms import TenantBrandForm
from tenants.models import Tenant

from .forms import CardDesignForm
from .models import CardArtifact, CardArtworkSource, CardDesign
from .services import (
    apply_brand_defaults,
    brand_snapshot_values,
    build_sample_sheet,
    calculate_crop_capacity,
    design_snapshot_values,
    inspect_artwork_source,
    publish_design_release,
    render_card,
    resolve_artifact_path,
    spec_from_values,
)


def _positive_form_value(form, field_name, fallback):
    try:
        return max(1, int(form[field_name].value()))
    except (TypeError, ValueError):
        return fallback


def _card_design_context(
    tenant,
    brand_form,
    design_form,
    proof=None,
    sample_sheet=None,
    crop_capacity=None,
):
    designs = CardDesign.objects.filter(tenant=tenant).select_related("brand_revision")
    current_design = designs.first()
    artwork_sources = list(CardArtworkSource.objects.filter(tenant=tenant))
    card_width = _positive_form_value(
        design_form, "width_px", current_design.width_px if current_design else 1011
    )
    card_height = _positive_form_value(
        design_form, "height_px", current_design.height_px if current_design else 638
    )
    planned_count = _positive_form_value(design_form, "planned_card_count", 600)
    selected_source_id = str(design_form["source_image"].value() or "")
    artwork_source_cards = []
    for source in artwork_sources:
        try:
            capacity = inspect_artwork_source(
                source,
                card_width=card_width,
                card_height=card_height,
                requested_count=planned_count,
            )
            unavailable = False
        except (OSError, ValueError):
            capacity = None
            unavailable = True
        artwork_source_cards.append(
            {
                "source": source,
                "capacity": capacity,
                "selected": str(source.pk) == selected_source_id,
                "unavailable": unavailable,
            }
        )
        if crop_capacity is None and str(source.pk) == selected_source_id:
            crop_capacity = capacity
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
        "crop_capacity": crop_capacity,
        "planned_card_count": planned_count,
        "artwork_source_cards": artwork_source_cards,
        "proof_artifacts": proof_artifacts,
        "active_nav": "card_design",
        "can_manage_integrations": True,
        "can_manage_card_designs": True,
        "can_manage_printing": True,
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
        return HttpResponseForbidden(
            _("Nie masz uprawnień do projektu kart tej firmy.")
        )
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
    crop_capacity = None
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
                background_source=(
                    design_form.cleaned_data["source_image"].image
                    if design_form.cleaned_data.get("source_image")
                    else None
                ),
                logo_upload=design_form.cleaned_data.get("logo_image"),
                fallback_design=current_design,
            )
            planned_count = design_form.cleaned_data["planned_card_count"]
            crop_capacity = calculate_crop_capacity(
                spec, requested_count=planned_count
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
                "crop_capacity": crop_capacity.metadata(),
            }
            sample_sheet = build_sample_sheet(
                spec,
                count=design_form.cleaned_data.get("sample_count") or 6,
                total_count=planned_count,
            )
            status = 200
            if request.POST.get("action") == "publish":
                design = publish_design_release(
                    tenant=tenant,
                    actor=request.user,
                    brand_values=brand_values,
                    design_values=design_values,
                    background_upload=design_form.cleaned_data.get("background_image"),
                    selected_source=design_form.cleaned_data.get("source_image"),
                    logo_upload=design_form.cleaned_data.get("logo_image"),
                )
                messages.success(
                    request,
                    _("Opublikowano projekt karty v%(version)s.")
                    % {"version": design.version},
                )
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
        crop_capacity,
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
        return HttpResponseForbidden(_("Nie masz dostępu do plików tej firmy."))
    artifact = get_object_or_404(CardArtifact, pk=artifact_id, tenant=tenant)
    path = resolve_artifact_path(artifact)
    if not path.is_file():
        raise Http404(_("Plik artefaktu nie istnieje."))
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return FileResponse(
        path.open("rb"),
        as_attachment=True,
        filename=path.name,
        content_type=content_type,
    )


@login_required
def card_artwork_source_preview(request, tenant_slug, source_id):
    tenant = get_object_or_404(Tenant, slug=tenant_slug, is_active=True)
    if not can_manage_card_designs(request.user, tenant):
        return HttpResponseForbidden(
            _("Nie masz dostępu do obrazów źródłowych tej firmy.")
        )
    source = get_object_or_404(
        CardArtworkSource,
        pk=source_id,
        tenant=tenant,
    )
    try:
        source.image.open("rb")
        with Image.open(source.image) as opened:
            thumbnail = ImageOps.exif_transpose(opened).convert("RGB")
            thumbnail.thumbnail((900, 900), Image.Resampling.LANCZOS)
            content = BytesIO()
            thumbnail.save(content, format="JPEG", quality=82, optimize=True)
    except OSError as exc:
        raise Http404(_("Plik obrazu źródłowego nie istnieje.")) from exc
    finally:
        source.image.close()
    response = HttpResponse(content.getvalue(), content_type="image/jpeg")
    response["Cache-Control"] = "private, max-age=3600"
    response["X-Content-Type-Options"] = "nosniff"
    return response
