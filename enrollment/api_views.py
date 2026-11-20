"""Tenant-scoped HTTP API for issuing virtual loyalty cards."""

import json
import re

from django.core.exceptions import ValidationError
from django.core.validators import EmailValidator
from django.http import JsonResponse
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from billing.services import EntitlementLimitError
from dotykacka.models import CardDesign

from .api_auth import api_error, virtual_card_key_required
from .models import VirtualCardApplication
from .services import (
    VirtualCardIdempotencyConflict,
    register_virtual_card,
    virtual_card_application_state,
    virtual_card_request_checksum,
)


IDEMPOTENCY_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{7,119}")
ALLOWED_FIELDS = {
    "first_name",
    "last_name",
    "email",
    "phone",
    "card_design_id",
    "marketing_consent",
}


def _design_payload(request, design):
    asset_base = {
        "tenant_slug": design.tenant.slug,
        "design_id": design.pk,
    }
    return {
        "id": design.pk,
        "name": design.name,
        "version": design.version,
        "foreground_color": design.foreground_color,
        "panel_color": design.panel_color,
        "background_url": request.build_absolute_uri(
            reverse(
                "enrollment:virtual_card_design_asset",
                kwargs={**asset_base, "asset_kind": "background"},
            )
        ) if design.background_source else None,
        "logo_url": request.build_absolute_uri(
            reverse(
                "enrollment:virtual_card_design_asset",
                kwargs={**asset_base, "asset_kind": "logo"},
            )
        ) if design.logo else None,
    }


def _application_payload(request, application):
    return {
        "request_id": str(application.public_id),
        "state": virtual_card_application_state(application),
        "email": application.customer.email,
        "card_design": {
            "id": application.card_design_id,
            "name": application.card_design.name,
        },
        "created_at": application.created_at.isoformat(),
        "status_url": request.build_absolute_uri(
            reverse(
                "virtual_cards_api:detail",
                kwargs={"public_id": application.public_id},
            )
        ),
    }


def _clean_payload(request):
    if request.content_type != "application/json":
        raise TypeError("Content-Type must be application/json.")
    if len(request.body) > 16 * 1024:
        raise ValueError("Request body is too large.")
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Request body must contain valid JSON.") from exc
    if not isinstance(payload, dict):
        raise ValueError("Request body must be a JSON object.")
    unknown = set(payload) - ALLOWED_FIELDS
    if unknown:
        raise ValueError(f"Unknown fields: {', '.join(sorted(unknown))}.")
    missing = ALLOWED_FIELDS - set(payload)
    if missing:
        raise ValueError(f"Missing fields: {', '.join(sorted(missing))}.")
    first_name = str(payload.get("first_name") or "").strip()
    last_name = str(payload.get("last_name") or "").strip()
    email = str(payload.get("email") or "").strip().lower()
    phone = re.sub(r"[\s()\-]", "", str(payload.get("phone") or "").strip())
    if not first_name or len(first_name) > 100:
        raise ValueError("first_name must contain between 1 and 100 characters.")
    if not last_name or len(last_name) > 100:
        raise ValueError("last_name must contain between 1 and 100 characters.")
    if len(email) > 100:
        raise ValueError("email is too long.")
    try:
        EmailValidator()(email)
    except ValidationError as exc:
        raise ValueError("email must be a valid email address.") from exc
    if not re.fullmatch(r"\+?[0-9]{8,15}", phone):
        raise ValueError("phone must contain between 8 and 15 digits.")
    if payload.get("marketing_consent") is not True:
        raise ValueError("marketing_consent must be true.")
    design_id = payload.get("card_design_id")
    if isinstance(design_id, bool):
        raise ValueError("card_design_id must be an integer.")
    try:
        design_id = int(design_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("card_design_id must be an integer.") from exc
    return {
        "first_name": first_name,
        "last_name": last_name,
        "email": email,
        "phone": phone,
        "card_design_id": design_id,
        "marketing_consent": True,
    }


@require_GET
@virtual_card_key_required
def design_list(request):
    designs = request.virtual_card_api_key.tenant.card_designs.select_related(
        "tenant"
    ).order_by("-version", "-pk")
    response = JsonResponse(
        {"results": [_design_payload(request, design) for design in designs]}
    )
    response["Cache-Control"] = "private, no-store"
    return response


@csrf_exempt
@require_POST
@virtual_card_key_required
def create_virtual_card(request):
    idempotency_key = request.headers.get("Idempotency-Key", "").strip()
    if not IDEMPOTENCY_PATTERN.fullmatch(idempotency_key):
        return api_error(
            "Idempotency-Key must contain 8-120 letters, digits, dots, colons, underscores, or hyphens.",
            status=400,
            code="invalid_idempotency_key",
        )
    try:
        cleaned = _clean_payload(request)
    except TypeError as exc:
        return api_error(str(exc), status=415, code="unsupported_media_type")
    except ValueError as exc:
        return api_error(str(exc), status=400, code="invalid_request")
    tenant = request.virtual_card_api_key.tenant
    try:
        design = CardDesign.objects.select_related("brand_revision").get(
            tenant=tenant,
            pk=cleaned["card_design_id"],
        )
    except CardDesign.DoesNotExist:
        return api_error(
            "card_design_id does not identify an available design.",
            status=400,
            code="invalid_card_design",
        )
    try:
        result = register_virtual_card(
            tenant=tenant,
            card_design=design,
            cleaned_data=cleaned,
            idempotency_key=f"api:{request.virtual_card_api_key.pk}:{idempotency_key}",
            request_sha256=virtual_card_request_checksum(cleaned),
            source=VirtualCardApplication.Source.API,
            api_key=request.virtual_card_api_key,
        )
    except VirtualCardIdempotencyConflict:
        return api_error(
            "Idempotency-Key was already used with different request data.",
            status=409,
            code="idempotency_conflict",
        )
    except EntitlementLimitError:
        return api_error(
            "The tenant card issuance limit has been reached.",
            status=409,
            code="issuance_limit_reached",
        )
    except ValidationError as exc:
        return api_error(
            "; ".join(exc.messages),
            status=409,
            code="issuance_unavailable",
        )
    application = VirtualCardApplication.objects.select_related(
        "customer", "card_design"
    ).prefetch_related("followups__integration_job").get(pk=result.application.pk)
    payload = _application_payload(request, application)
    response = JsonResponse(
        payload,
        status=202 if result.created else 200,
    )
    response["Cache-Control"] = "no-store"
    response["Location"] = payload["status_url"]
    return response


@require_GET
@virtual_card_key_required
def virtual_card_detail(request, public_id):
    application = (
        VirtualCardApplication.objects.select_related("customer", "card_design").prefetch_related(
            "followups__integration_job"
        ).filter(
            public_id=public_id,
            tenant=request.virtual_card_api_key.tenant,
            api_key=request.virtual_card_api_key,
        ).first()
    )
    if application is None:
        return api_error(
            "Virtual-card request was not found.",
            status=404,
            code="not_found",
        )
    response = JsonResponse(_application_payload(request, application))
    response["Cache-Control"] = "private, no-store"
    return response


__all__ = ["create_virtual_card", "design_list", "virtual_card_detail"]
