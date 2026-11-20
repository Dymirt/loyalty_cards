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
from dotykacka.models import PhysicalCard
from .api_auth import api_error, virtual_card_key_required
from .catalog import virtual_card_designs
from .models import VirtualCardApplication
from .services import (
    VirtualCardIdempotencyConflict,
    register_virtual_card,
    virtual_card_application_state,
    virtual_card_request_checksum,
)


IDEMPOTENCY_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{7,119}")
REQUIRED_FIELDS = {
    "first_name",
    "last_name",
    "email",
    "phone",
    "marketing_consent",
}
SELECTION_FIELDS = {"card_id", "card_code", "card_design_id"}
ALLOWED_FIELDS = REQUIRED_FIELDS | SELECTION_FIELDS


def _card_payload(request, card):
    asset_base = {
        "tenant_slug": card.tenant.slug,
        "card_id": card.pk,
    }
    front_url = request.build_absolute_uri(
        reverse(
            "enrollment:virtual_card_asset",
            kwargs={**asset_base, "asset_kind": "front"},
        )
    )
    return {
        "id": card.pk,
        "name": card.code,
        "card_code": card.code,
        "preview_url": front_url,
        "front_url": front_url,
        "back_url": request.build_absolute_uri(
            reverse(
                "enrollment:virtual_card_asset",
                kwargs={**asset_base, "asset_kind": "back"},
            )
        ),
    }


def _application_payload(request, application):
    customer = application.customer
    wallet = getattr(customer, "wallet_pass", None)
    jobs_by_kind = {
        followup.kind: followup.integration_job
        for followup in application.followups.all()
    }

    def delivery(kind, *, ready=False, identifier=None):
        job = jobs_by_kind.get(kind)
        return {
            "status": job.status if job else "not_requested",
            "ready": bool(
                ready or (job and job.status == "succeeded")
            ),
            "identifier": str(identifier) if identifier else None,
            "last_error_code": job.last_error_code if job else "",
        }

    apple_ready = bool(wallet and wallet.apple_pass_path)
    google_ready = bool(wallet and wallet.google_save_url)
    selected_card = application.physical_card
    selected_payload = (
        _card_payload(request, selected_card)
        if selected_card is not None
        else {
            "id": application.card_design_id,
            "name": application.card_design.name,
            "card_code": customer.klient_id,
            "preview_url": None,
            "front_url": None,
            "back_url": None,
        }
    )
    return {
        "request_id": str(application.public_id),
        "state": virtual_card_application_state(application),
        "card_id": customer.klient_id,
        "card_created": wallet is not None,
        "email": customer.email,
        "card": {
            "id": customer.klient_id,
            "created": wallet is not None,
            "wallet_pass_id": str(wallet.apple_serial) if wallet else None,
            "inventory_card_id": getattr(selected_card, "pk", None),
            "front_url": selected_payload["front_url"],
            "back_url": selected_payload["back_url"],
        },
        "card_design": selected_payload,
        "delivery": {
            "apple_wallet": delivery(
                "wallet.apple.issue",
                ready=apple_ready,
                identifier=wallet.apple_serial if wallet else None,
            ),
            "google_wallet": delivery(
                "wallet.google.issue",
                ready=google_ready,
                identifier=wallet.google_object_id if wallet else None,
            ),
            "email": delivery("communications.email.pass"),
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
    missing = REQUIRED_FIELDS - set(payload)
    if missing:
        raise ValueError(f"Missing fields: {', '.join(sorted(missing))}.")
    selected_fields = SELECTION_FIELDS & set(payload)
    if len(selected_fields) != 1:
        raise ValueError(
            "Provide exactly one of card_code, card_id, or card_design_id."
        )
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
    selection_field = selected_fields.pop()
    cleaned = {
        "first_name": first_name,
        "last_name": last_name,
        "email": email,
        "phone": phone,
        "marketing_consent": True,
    }
    if selection_field == "card_code":
        card_code = str(payload.get("card_code") or "").strip().upper()
        if not card_code or len(card_code) > 60:
            raise ValueError("card_code must identify an available card.")
        cleaned["card_code"] = card_code
    else:
        card_id = payload.get(selection_field)
        if isinstance(card_id, bool):
            raise ValueError(f"{selection_field} must be an integer.")
        try:
            card_id = int(card_id)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{selection_field} must be an integer.") from exc
        cleaned["card_id"] = card_id
    return cleaned


@require_GET
@virtual_card_key_required
def design_list(request):
    cards = virtual_card_designs(request.virtual_card_api_key.tenant)
    response = JsonResponse(
        {"results": [_card_payload(request, card) for card in cards]}
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
        selected_card = tenant.physical_cards.get(
            **(
                {"pk": cleaned["card_id"]}
                if "card_id" in cleaned
                else {"code": cleaned["card_code"]}
            )
        )
    except PhysicalCard.DoesNotExist:
        return api_error(
            "The selected card does not belong to this tenant.",
            status=400,
            code="invalid_card",
        )
    cleaned.update({"card_id": selected_card.pk, "card_code": selected_card.code})
    try:
        result = register_virtual_card(
            tenant=tenant,
            physical_card=selected_card,
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
    except PhysicalCard.DoesNotExist:
        return api_error(
            "The selected card is no longer available.",
            status=409,
            code="card_unavailable",
        )
    except ValidationError as exc:
        return api_error(
            "; ".join(exc.messages),
            status=409,
            code="issuance_unavailable",
        )
    application = VirtualCardApplication.objects.select_related(
        "customer__wallet_pass", "card_design", "physical_card__tenant"
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
        VirtualCardApplication.objects.select_related(
            "customer__wallet_pass", "card_design", "physical_card__tenant"
        ).prefetch_related(
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
