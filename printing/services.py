"""Transactional centralized-printing application services."""

from __future__ import annotations

import hashlib
import json
import os
import socket
import tempfile
import zipfile
from collections import Counter
from datetime import timedelta
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import connection as database_connection
from django.db import transaction
from django.db.models import F, Max, Q
from django.utils import timezone
from PIL import Image

from billing.models import Quote
from billing.services import consume_print_quote
from card_artwork.models import CardArtifact, CardDesign, CropPlan
from card_artwork.services import bytes_sha256, generate_card_artifacts, resolve_artifact_path
from cards.models import CardBatch, PhysicalCard
from dotykacka.models import AuditEvent
from tenants.models import Tenant

from .models import (
    FulfillmentEvent,
    PrintJob,
    PrintPackage,
    PrintRequest,
    PrintRequestEvent,
    PrintRun,
    PrintRunCard,
)


LAYOUT_VERSION = "per-card-jpeg-zip-v1"


REQUEST_TRANSITIONS = {
    PrintRequest.Status.SUBMITTED: {
        PrintRequest.Status.APPROVED,
        PrintRequest.Status.REJECTED,
        PrintRequest.Status.CANCELLED,
    },
    PrintRequest.Status.APPROVED: {
        PrintRequest.Status.ALLOCATED,
        PrintRequest.Status.CANCELLED,
    },
    PrintRequest.Status.ALLOCATED: {
        PrintRequest.Status.GENERATING,
        PrintRequest.Status.FAILED,
        PrintRequest.Status.CANCELLED,
    },
    PrintRequest.Status.GENERATING: {
        PrintRequest.Status.READY,
        PrintRequest.Status.FAILED,
    },
    PrintRequest.Status.FAILED: {PrintRequest.Status.GENERATING},
    PrintRequest.Status.READY: {
        PrintRequest.Status.PRINTING,
        PrintRequest.Status.CANCELLED,
    },
    PrintRequest.Status.PRINTING: {PrintRequest.Status.PRINTED},
    PrintRequest.Status.PRINTED: {PrintRequest.Status.PACKED},
    PrintRequest.Status.PACKED: {PrintRequest.Status.DISPATCHED},
    PrintRequest.Status.DISPATCHED: {PrintRequest.Status.DELIVERED},
}


FULFILLMENT_TRANSITIONS = {
    FulfillmentEvent.Kind.PRINTING: (
        PrintRequest.Status.READY,
        PrintRequest.Status.PRINTING,
    ),
    FulfillmentEvent.Kind.PRINTED: (
        PrintRequest.Status.PRINTING,
        PrintRequest.Status.PRINTED,
    ),
    FulfillmentEvent.Kind.PACKED: (
        PrintRequest.Status.PRINTED,
        PrintRequest.Status.PACKED,
    ),
    FulfillmentEvent.Kind.DISPATCHED: (
        PrintRequest.Status.PACKED,
        PrintRequest.Status.DISPATCHED,
    ),
    FulfillmentEvent.Kind.DELIVERED: (
        PrintRequest.Status.DISPATCHED,
        PrintRequest.Status.DELIVERED,
    ),
}


def _canonical_sha256(value):
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _design_snapshot(design):
    return {
        "id": design.pk,
        "version": design.version,
        "checksum": design.design_checksum,
        "brand_revision_id": design.brand_revision_id,
        "name": design.name,
        "layout_preset": design.layout_preset,
        "crop_mode": design.crop_mode,
        "width_px": design.width_px,
        "height_px": design.height_px,
        "dpi": design.dpi,
        "bleed_mm": str(design.bleed_mm),
        "font_family": design.font_family,
    }


def _quote_snapshot(quote):
    return {
        "id": quote.pk,
        "status": quote.status,
        "accepted_at": quote.accepted_at.isoformat() if quote.accepted_at else None,
        "quantity": quote.quantity,
        "included_quantity": quote.included_quantity,
        "pack_quantity": quote.pack_quantity,
        "billable_quantity": quote.billable_quantity,
        "currency": quote.currency,
        "subtotal_amount": str(quote.subtotal_amount),
        "shipping_amount": str(quote.shipping_amount),
        "tax_amount": str(quote.tax_amount),
        "total_amount": str(quote.total_amount),
        "commercial_snapshot": quote.snapshot,
        "lines": [
            {
                "position": line.position,
                "kind": line.kind,
                "description": line.description,
                "quantity": line.quantity,
                "unit_amount": str(line.unit_amount),
                "total_amount": str(line.total_amount),
                "metadata": line.metadata,
            }
            for line in quote.lines.all()
        ],
    }


def _layout_snapshot(design):
    return {
        "version": LAYOUT_VERSION,
        "mode": "per_card_files",
        "archive_format": "zip",
        "front_format": "jpeg",
        "back_format": "jpeg",
        "barcode_format": "png",
        "width_px": design.width_px,
        "height_px": design.height_px,
        "dpi": design.dpi,
        "bleed_mm": str(design.bleed_mm),
        "color_mode": "RGB",
        "color_profile": "unmanaged_srgb_compatible",
        "sheet_imposition": None,
        "duplex_flip": None,
        "crop_marks": False,
    }


def _latest_proofs(*, tenant, design):
    front = CardArtifact.objects.filter(
        tenant=tenant,
        design=design,
        kind=CardArtifact.Kind.PROOF_FRONT,
    ).first()
    back = CardArtifact.objects.filter(
        tenant=tenant,
        design=design,
        kind=CardArtifact.Kind.PROOF_BACK,
    ).first()
    if front is None or back is None:
        raise ValidationError(
            "The selected design needs immutable front and back proof artifacts."
        )
    return front, back


def _transition_request(*, print_request, to_status, actor=None, reason="", metadata=None):
    if print_request.status == to_status:
        return print_request, False
    allowed = REQUEST_TRANSITIONS.get(print_request.status, set())
    if to_status not in allowed:
        raise ValidationError(
            f"Print request cannot move from {print_request.status} to {to_status}."
        )
    previous = print_request.status
    print_request.status = to_status
    print_request.save(update_fields=("status", "updated_at"))
    PrintRequestEvent.objects.create(
        print_request=print_request,
        from_status=previous,
        to_status=to_status,
        actor=actor,
        reason=reason,
        metadata=metadata or {},
    )
    return print_request, True


@transaction.atomic
def submit_print_request(
    *,
    tenant,
    design,
    quote,
    requested_by,
    idempotency_key,
    proof_approved,
    delivery_name,
    delivery_address_line1,
    delivery_address_line2="",
    delivery_postal_code,
    delivery_city,
    delivery_country="PL",
    notes="",
):
    if not proof_approved:
        raise ValidationError("The tenant owner must approve the frozen proof.")
    tenant = Tenant.objects.select_for_update().get(pk=tenant.pk)
    existing = PrintRequest.objects.filter(
        tenant=tenant,
        idempotency_key=idempotency_key,
    ).first()
    if existing:
        if existing.design_id != design.pk or existing.quote_id != quote.pk:
            raise ValidationError(
                "This print-request idempotency key was used for another request."
            )
        return existing, False
    design = CardDesign.objects.select_related("brand_revision").get(
        pk=design.pk,
        tenant=tenant,
    )
    quote = (
        Quote.objects.select_for_update()
        .select_related("subscription", "billing_period", "price_book_version")
        .prefetch_related("lines")
        .get(pk=quote.pk, tenant=tenant)
    )
    if quote.status != Quote.Status.ACCEPTED or not quote.accepted_at:
        raise ValidationError("Select an accepted immutable print quote.")
    if PrintRequest.objects.filter(quote=quote).exists():
        raise ValidationError("This accepted quote already belongs to a print request.")
    front, back = _latest_proofs(tenant=tenant, design=design)
    proof_checksum = _canonical_sha256(
        {"front": front.sha256, "back": back.sha256}
    )
    snapshot = {
        "proof": {
            "front_artifact_id": front.pk,
            "front_sha256": front.sha256,
            "back_artifact_id": back.pk,
            "back_sha256": back.sha256,
            "combined_sha256": proof_checksum,
        },
        "design": _design_snapshot(design),
        "quote": _quote_snapshot(quote),
        "delivery": {
            "name": delivery_name,
            "address_line1": delivery_address_line1,
            "address_line2": delivery_address_line2,
            "postal_code": delivery_postal_code,
            "city": delivery_city,
            "country": delivery_country.upper(),
        },
        "notes": notes,
    }
    print_request = PrintRequest(
        tenant=tenant,
        design=design,
        proof_front=front,
        proof_back=back,
        quote=quote,
        requested_by=requested_by,
        idempotency_key=idempotency_key,
        quantity=quote.quantity,
        proof_checksum=proof_checksum,
        delivery_name=delivery_name,
        delivery_address_line1=delivery_address_line1,
        delivery_address_line2=delivery_address_line2,
        delivery_postal_code=delivery_postal_code,
        delivery_city=delivery_city,
        delivery_country=delivery_country,
        notes=notes,
        snapshot=snapshot,
    )
    print_request.full_clean()
    print_request.save()
    PrintRequestEvent.objects.create(
        print_request=print_request,
        from_status="",
        to_status=PrintRequest.Status.SUBMITTED,
        actor=requested_by,
        metadata={"proof_checksum": proof_checksum, "quote_id": quote.pk},
    )
    AuditEvent.objects.create(
        tenant=tenant,
        actor=requested_by,
        action="printing.request_submitted",
        object_type="PrintRequest",
        object_id=str(print_request.pk),
        metadata={
            "quantity": print_request.quantity,
            "design_id": design.pk,
            "quote_id": quote.pk,
            "proof_checksum": proof_checksum,
        },
    )
    return print_request, True


@transaction.atomic
def approve_print_request(*, print_request, actor, reason=""):
    print_request = PrintRequest.objects.select_for_update().get(pk=print_request.pk)
    result = _transition_request(
        print_request=print_request,
        to_status=PrintRequest.Status.APPROVED,
        actor=actor,
        reason=reason,
    )
    if result[1]:
        AuditEvent.objects.create(
            tenant=print_request.tenant,
            actor=actor,
            action="printing.request_approved",
            object_type="PrintRequest",
            object_id=str(print_request.pk),
            metadata={"proof_checksum": print_request.proof_checksum},
        )
    return result


@transaction.atomic
def reject_print_request(*, print_request, actor, reason):
    if not reason.strip():
        raise ValidationError("A rejection reason is required.")
    print_request = PrintRequest.objects.select_for_update().get(pk=print_request.pk)
    result = _transition_request(
        print_request=print_request,
        to_status=PrintRequest.Status.REJECTED,
        actor=actor,
        reason=reason,
    )
    if result[1]:
        AuditEvent.objects.create(
            tenant=print_request.tenant,
            actor=actor,
            action="printing.request_rejected",
            object_type="PrintRequest",
            object_id=str(print_request.pk),
            metadata={"reason": reason},
        )
    return result


@transaction.atomic
def allocate_print_run(*, print_request, actor):
    print_request = (
        PrintRequest.objects.select_for_update()
        .select_related("tenant", "design", "quote")
        .get(pk=print_request.pk)
    )
    try:
        return print_request.print_run, False
    except PrintRun.DoesNotExist:
        pass
    if print_request.status != PrintRequest.Status.APPROVED:
        raise ValidationError("Only an approved print request can be allocated.")
    tenant = Tenant.objects.select_for_update().get(pk=print_request.tenant_id)
    highest = (
        PhysicalCard.objects.filter(tenant=tenant).aggregate(value=Max("number"))[
            "value"
        ]
        or 0
    )
    start_number = highest + 1
    end_number = highest + print_request.quantity
    design_snapshot = _design_snapshot(print_request.design)
    quote = Quote.objects.select_for_update().prefetch_related("lines").get(
        pk=print_request.quote_id
    )
    quote_snapshot = _quote_snapshot(quote)
    layout_snapshot = _layout_snapshot(print_request.design)
    batch = CardBatch.objects.create(
        tenant=tenant,
        design=print_request.design,
        name=f"print-request-{print_request.pk}-{start_number}-{end_number}",
        card_prefix=tenant.card_prefix,
        start_number=start_number,
        end_number=end_number,
        status=CardBatch.Status.DRAFT,
        design_snapshot={
            "design": design_snapshot,
            "quote": quote_snapshot,
            "layout": layout_snapshot,
            "print_request_id": print_request.pk,
        },
    )
    cards = [
        PhysicalCard(
            tenant=tenant,
            batch=batch,
            code=f"{tenant.card_prefix}-{number}",
            number=number,
            status=PhysicalCard.Status.AVAILABLE,
        )
        for number in range(start_number, end_number + 1)
    ]
    PhysicalCard.objects.bulk_create(cards)
    run = PrintRun(
        print_request=print_request,
        tenant=tenant,
        design=print_request.design,
        quote=quote,
        batch=batch,
        created_by=actor,
        quantity=print_request.quantity,
        start_number=start_number,
        end_number=end_number,
        layout_snapshot=layout_snapshot,
        design_snapshot=design_snapshot,
        quote_snapshot=quote_snapshot,
    )
    run.full_clean()
    run.save()
    PrintRunCard.objects.bulk_create(
        [
            PrintRunCard(
                print_run=run,
                physical_card=card,
                position=position,
                code_snapshot=card.code,
            )
            for position, card in enumerate(cards, 1)
        ]
    )
    consume_print_quote(
        quote=quote,
        reference_type="PrintRun",
        reference_id=run.pk,
    )
    job = PrintJob.objects.create(
        print_run=run,
        idempotency_key=f"print-run:{run.pk}:generation:1",
    )
    _transition_request(
        print_request=print_request,
        to_status=PrintRequest.Status.ALLOCATED,
        actor=actor,
        metadata={
            "run_id": run.pk,
            "job_id": job.pk,
            "start_number": start_number,
            "end_number": end_number,
        },
    )
    AuditEvent.objects.create(
        tenant=tenant,
        actor=actor,
        action="printing.run_allocated",
        object_type="PrintRun",
        object_id=str(run.pk),
        metadata={
            "request_id": print_request.pk,
            "quantity": run.quantity,
            "start_number": start_number,
            "end_number": end_number,
            "quote_id": quote.pk,
        },
    )
    return run, True


@transaction.atomic
def cancel_print_request(*, print_request, actor, reason):
    if not reason.strip():
        raise ValidationError("A cancellation reason is required.")
    print_request = PrintRequest.objects.select_for_update().get(pk=print_request.pk)
    if print_request.status not in {
        PrintRequest.Status.SUBMITTED,
        PrintRequest.Status.APPROVED,
        PrintRequest.Status.ALLOCATED,
        PrintRequest.Status.READY,
    }:
        raise ValidationError("This request can no longer be cancelled.")
    if hasattr(print_request, "print_run"):
        run = PrintRun.objects.select_for_update().get(pk=print_request.print_run.pk)
        if run.status == PrintRun.Status.GENERATING:
            raise ValidationError("A generating run cannot be cancelled.")
        PrintJob.objects.filter(
            print_run=run,
            status__in=(PrintJob.Status.PENDING, PrintJob.Status.RETRY),
        ).update(
            status=PrintJob.Status.CANCELLED,
            finished_at=timezone.now(),
            updated_at=timezone.now(),
        )
        run.status = PrintRun.Status.CANCELLED
        run.completed_at = timezone.now()
        run.save(update_fields=("status", "completed_at", "updated_at"))
        PhysicalCard.objects.filter(
            production_allocation__print_run=run,
            status=PhysicalCard.Status.AVAILABLE,
            customer__isnull=True,
        ).update(status=PhysicalCard.Status.VOID)
    result = _transition_request(
        print_request=print_request,
        to_status=PrintRequest.Status.CANCELLED,
        actor=actor,
        reason=reason,
    )
    AuditEvent.objects.create(
        tenant=print_request.tenant,
        actor=actor,
        action="printing.request_cancelled",
        object_type="PrintRequest",
        object_id=str(print_request.pk),
        metadata={"reason": reason},
    )
    return result


@transaction.atomic
def claim_next_print_job(*, worker_id, stale_after=timedelta(minutes=15)):
    now = timezone.now()
    stale_before = now - stale_after
    stale_final_jobs = list(PrintJob.objects.select_for_update().filter(
        status=PrintJob.Status.RUNNING,
        locked_at__lt=stale_before,
        attempts__gte=F("max_attempts"),
    ))
    for stale_job in stale_final_jobs:
        run = PrintRun.objects.select_for_update().get(pk=stale_job.print_run_id)
        if PrintPackage.objects.filter(print_run=run).exists():
            stale_job.status = PrintJob.Status.SUCCEEDED
            stale_job.last_error_code = ""
        else:
            stale_job.status = PrintJob.Status.FAILED
            stale_job.last_error_code = "worker_lost_after_final_attempt"
            run.status = PrintRun.Status.FAILED
            run.completed_at = now
            run.save(update_fields=("status", "completed_at", "updated_at"))
            print_request = PrintRequest.objects.select_for_update().get(
                pk=run.print_request_id
            )
            if print_request.status in {
                PrintRequest.Status.ALLOCATED,
                PrintRequest.Status.GENERATING,
            }:
                _transition_request(
                    print_request=print_request,
                    to_status=PrintRequest.Status.FAILED,
                    reason="Production worker was lost after its final attempt.",
                    metadata={"job_id": stale_job.pk},
                )
        stale_job.finished_at = now
        stale_job.locked_at = None
        stale_job.locked_by = ""
        stale_job.save(
            update_fields=(
                "status",
                "finished_at",
                "locked_at",
                "locked_by",
                "last_error_code",
                "updated_at",
            )
        )
    eligible = Q(status__in=(PrintJob.Status.PENDING, PrintJob.Status.RETRY)) | Q(
        status=PrintJob.Status.RUNNING,
        locked_at__lt=stale_before,
    )
    queryset = PrintJob.objects.filter(
        eligible,
        available_at__lte=now,
        attempts__lt=F("max_attempts"),
    )
    if database_connection.features.has_select_for_update:
        queryset = queryset.select_for_update(
            skip_locked=database_connection.features.has_select_for_update_skip_locked
        )
    job = queryset.order_by("available_at", "created_at", "pk").first()
    if job is None:
        return None
    job.status = PrintJob.Status.RUNNING
    job.attempts += 1
    job.locked_at = now
    job.locked_by = worker_id
    job.last_error_code = ""
    job.save(
        update_fields=(
            "status",
            "attempts",
            "locked_at",
            "locked_by",
            "last_error_code",
            "updated_at",
        )
    )
    return job


def _validate_image(content, *, width, height, dpi, label):
    with Image.open(BytesIO(content)) as image:
        if image.size != (width, height):
            raise ValidationError(f"{label} has unexpected dimensions.")
        stored_dpi = image.info.get("dpi", (0, 0))
        if not stored_dpi or any(abs(float(value) - dpi) > 2 for value in stored_dpi[:2]):
            raise ValidationError(f"{label} has unexpected DPI metadata.")


def _artifact_content(artifact):
    path = resolve_artifact_path(artifact)
    if not path.is_file():
        raise ValidationError(f"Missing production artifact {artifact.pk}.")
    content = path.read_bytes()
    if len(content) != artifact.size_bytes or bytes_sha256(content) != artifact.sha256:
        raise ValidationError(f"Production artifact {artifact.pk} failed checksum validation.")
    return content


def _zip_entry(archive, name, content):
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    archive.writestr(info, content)


def _package_relative_path(run, job):
    return Path(
        f"tenants/{run.tenant.slug}/printing/requests/{run.print_request_id}/"
        f"runs/{run.pk}/jobs/{job.pk}/production.zip"
    )


def _publish_package_file(relative_path, content):
    package_root = Path(settings.PRINT_PACKAGE_ROOT).resolve()
    final_path = (package_root / relative_path).resolve()
    if package_root not in final_path.parents:
        raise ValidationError("Unsafe print-package path.")
    final_path.parent.mkdir(parents=True, exist_ok=True)
    if final_path.exists():
        existing = final_path.read_bytes()
        if bytes_sha256(existing) != bytes_sha256(content):
            raise ValidationError("An immutable package path already contains different bytes.")
        return final_path
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".production-",
        suffix=".zip",
        dir=final_path.parent,
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary_name, final_path)
        except FileExistsError:
            existing = final_path.read_bytes()
            if bytes_sha256(existing) != bytes_sha256(content):
                raise ValidationError(
                    "An immutable package path already contains different bytes."
                )
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)
    return final_path


@transaction.atomic
def generate_print_package(*, job):
    job = PrintJob.objects.select_for_update().select_related(
        "print_run__print_request",
        "print_run__tenant",
        "print_run__design",
    ).get(pk=job.pk)
    run = PrintRun.objects.select_for_update().get(pk=job.print_run_id)
    print_request = PrintRequest.objects.select_for_update().get(pk=run.print_request_id)
    try:
        return run.package
    except PrintPackage.DoesNotExist:
        pass
    if job.status != PrintJob.Status.RUNNING:
        raise ValidationError("Only a claimed print job can generate a package.")
    if print_request.status == PrintRequest.Status.ALLOCATED:
        _transition_request(
            print_request=print_request,
            to_status=PrintRequest.Status.GENERATING,
            metadata={"run_id": run.pk, "job_id": job.pk},
        )
    elif print_request.status not in {
        PrintRequest.Status.GENERATING,
        PrintRequest.Status.FAILED,
    }:
        raise ValidationError("Print request is not ready for package generation.")
    if print_request.status == PrintRequest.Status.FAILED:
        _transition_request(
            print_request=print_request,
            to_status=PrintRequest.Status.GENERATING,
            metadata={"run_id": run.pk, "job_id": job.pk, "retry": True},
        )
    run.status = PrintRun.Status.GENERATING
    run.started_at = run.started_at or timezone.now()
    run.save(update_fields=("status", "started_at", "updated_at"))

    archive_files = {}
    card_manifest = []
    run_cards = list(
        PrintRunCard.objects.select_for_update()
        .select_related("physical_card")
        .filter(print_run=run)
        .order_by("position")
    )
    if len(run_cards) != run.quantity:
        raise ValidationError("Allocated card count does not match the run quantity.")
    if len({item.code_snapshot for item in run_cards}) != run.quantity:
        raise ValidationError("Allocated card codes are not unique.")

    for run_card in run_cards:
        artifacts = generate_card_artifacts(
            design=run.design,
            physical_card=run_card.physical_card,
        )
        by_kind = {artifact.kind: artifact for artifact in artifacts}
        front = by_kind[CardArtifact.Kind.CARD_FRONT]
        back = by_kind[CardArtifact.Kind.CARD_BACK]
        barcode = by_kind[CardArtifact.Kind.BARCODE]
        crop_plan = CropPlan.objects.get(pk=front.metadata["crop_plan_id"])
        run_card.crop_plan = crop_plan
        run_card.front_artifact = front
        run_card.back_artifact = back
        run_card.barcode_artifact = barcode
        run_card.full_clean()
        run_card.save(
            update_fields=(
                "crop_plan",
                "front_artifact",
                "back_artifact",
                "barcode_artifact",
            )
        )
        contents = {
            "front.jpg": _artifact_content(front),
            "back.jpg": _artifact_content(back),
            "barcode.png": _artifact_content(barcode),
        }
        _validate_image(
            contents["front.jpg"],
            width=run.design.width_px,
            height=run.design.height_px,
            dpi=run.design.dpi,
            label=f"{run_card.code_snapshot} front",
        )
        _validate_image(
            contents["back.jpg"],
            width=run.design.width_px,
            height=run.design.height_px,
            dpi=run.design.dpi,
            label=f"{run_card.code_snapshot} back",
        )
        file_rows = {}
        for filename, content in sorted(contents.items()):
            archive_name = f"cards/{run_card.code_snapshot}/{filename}"
            archive_files[archive_name] = content
            artifact = {
                "front.jpg": front,
                "back.jpg": back,
                "barcode.png": barcode,
            }[filename]
            file_rows[filename] = {
                "archive_path": archive_name,
                "artifact_id": artifact.pk,
                "sha256": bytes_sha256(content),
                "size_bytes": len(content),
            }
        card_manifest.append(
            {
                "position": run_card.position,
                "physical_card_id": run_card.physical_card_id,
                "code": run_card.code_snapshot,
                "number": run_card.physical_card.number,
                "crop_plan_id": crop_plan.pk,
                "crop_plan": {
                    "seed": crop_plan.seed,
                    "source_sha256": crop_plan.source_sha256,
                    "crop_box": list(crop_plan.crop_box),
                    "render_version": crop_plan.render_version,
                },
                "files": file_rows,
            }
        )

    manifest = {
        "schema": "loyalty-print-package/v1",
        "tenant": {"id": run.tenant_id, "slug": run.tenant.slug},
        "print_request": {
            "id": print_request.pk,
            "idempotency_key": print_request.idempotency_key,
            "proof_checksum": print_request.proof_checksum,
            "submitted_at": print_request.submitted_at.isoformat(),
        },
        "print_run": {
            "id": run.pk,
            "batch_id": run.batch_id,
            "quantity": run.quantity,
            "card_prefix": run.batch.card_prefix,
            "start_number": run.start_number,
            "end_number": run.end_number,
        },
        "design": run.design_snapshot,
        "quote": run.quote_snapshot,
        "layout": run.layout_snapshot,
        "delivery": print_request.snapshot["delivery"],
        "cards": card_manifest,
        "file_count": len(archive_files) + 2,
    }
    manifest_bytes = json.dumps(
        manifest,
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
    ).encode("utf-8")
    summary = (
        f"Loyalty Studio production run {run.pk}\n"
        f"Tenant: {run.tenant.name} ({run.tenant.slug})\n"
        f"Request: {print_request.pk}\n"
        f"Quantity: {run.quantity}\n"
        f"Codes: {run.batch.card_prefix}-{run.start_number} .. "
        f"{run.batch.card_prefix}-{run.end_number}\n"
        f"Design: v{run.design.version} {run.design.design_checksum}\n"
        f"Proof: {print_request.proof_checksum}\n"
        f"Layout: {run.layout_snapshot['version']}\n"
    ).encode("utf-8")
    archive_files["manifest.json"] = manifest_bytes
    archive_files["job-summary.txt"] = summary
    stream = BytesIO()
    with zipfile.ZipFile(stream, mode="w") as archive:
        for name, content in sorted(archive_files.items()):
            _zip_entry(archive, name, content)
    package_bytes = stream.getvalue()
    relative_path = _package_relative_path(run, job)
    _publish_package_file(relative_path, package_bytes)
    now = timezone.now()
    package = PrintPackage(
        print_run=run,
        storage_path=str(relative_path),
        sha256=bytes_sha256(package_bytes),
        size_bytes=len(package_bytes),
        manifest=manifest,
        validated_at=now,
    )
    package.full_clean()
    package.save()
    run.status = PrintRun.Status.READY
    run.validated_at = now
    run.completed_at = now
    run.batch.status = CardBatch.Status.GENERATED
    run.batch.save(update_fields=("status",))
    run.save(
        update_fields=(
            "status",
            "validated_at",
            "completed_at",
            "updated_at",
        )
    )
    _transition_request(
        print_request=print_request,
        to_status=PrintRequest.Status.READY,
        metadata={
            "run_id": run.pk,
            "package_id": package.pk,
            "package_sha256": package.sha256,
        },
    )
    AuditEvent.objects.create(
        tenant=run.tenant,
        actor=None,
        action="printing.package_validated",
        object_type="PrintPackage",
        object_id=str(package.pk),
        metadata={
            "request_id": print_request.pk,
            "run_id": run.pk,
            "quantity": run.quantity,
            "sha256": package.sha256,
        },
    )
    return package


def complete_print_job(job):
    now = timezone.now()
    PrintJob.objects.filter(
        pk=job.pk,
        status=PrintJob.Status.RUNNING,
    ).update(
        status=PrintJob.Status.SUCCEEDED,
        finished_at=now,
        locked_at=None,
        locked_by="",
        last_error_code="",
        updated_at=now,
    )


@transaction.atomic
def fail_print_job(job, exc):
    now = timezone.now()
    job = PrintJob.objects.select_for_update().get(pk=job.pk)
    if job.status != PrintJob.Status.RUNNING:
        return job
    error_code = type(exc).__name__[:80]
    if job.attempts < job.max_attempts:
        job.status = PrintJob.Status.RETRY
        job.available_at = now + timedelta(seconds=min(2**job.attempts, 300))
        job.finished_at = None
    else:
        job.status = PrintJob.Status.FAILED
        job.finished_at = now
        run = PrintRun.objects.select_for_update().get(pk=job.print_run_id)
        run.status = PrintRun.Status.FAILED
        run.completed_at = now
        run.save(update_fields=("status", "completed_at", "updated_at"))
        print_request = PrintRequest.objects.select_for_update().get(
            pk=run.print_request_id
        )
        if print_request.status in {
            PrintRequest.Status.ALLOCATED,
            PrintRequest.Status.GENERATING,
        }:
            _transition_request(
                print_request=print_request,
                to_status=PrintRequest.Status.FAILED,
                reason="Production package generation failed.",
                metadata={"error_code": error_code, "job_id": job.pk},
            )
    job.locked_at = None
    job.locked_by = ""
    job.last_error_code = error_code
    job.save(
        update_fields=(
            "status",
            "available_at",
            "finished_at",
            "locked_at",
            "locked_by",
            "last_error_code",
            "updated_at",
        )
    )
    return job


def process_next_print_job(*, worker_id=None):
    worker_id = worker_id or f"{socket.gethostname()}:{os.getpid()}:{uuid4().hex[:8]}"
    job = claim_next_print_job(worker_id=worker_id)
    if job is None:
        return None
    try:
        generate_print_package(job=job)
    except Exception as exc:
        fail_print_job(job, exc)
        raise
    complete_print_job(job)
    return job


def resolve_package_path(package):
    package_root = Path(settings.PRINT_PACKAGE_ROOT).resolve()
    path = (package_root / package.storage_path).resolve()
    if package_root not in path.parents:
        raise ValidationError("Unsafe print-package path.")
    return path


@transaction.atomic
def record_fulfillment(
    *,
    print_request,
    event_type,
    actor,
    idempotency_key,
    occurred_at=None,
    reference="",
    notes="",
):
    if event_type not in FULFILLMENT_TRANSITIONS:
        raise ValidationError("Unsupported fulfillment transition.")
    print_request = PrintRequest.objects.select_for_update().get(pk=print_request.pk)
    source, target = FULFILLMENT_TRANSITIONS[event_type]
    existing = FulfillmentEvent.objects.filter(
        tenant=print_request.tenant,
        idempotency_key=idempotency_key,
    ).first()
    if existing:
        return existing, False
    if print_request.status != source:
        raise ValidationError(
            f"Fulfillment {event_type} requires request status {source}."
        )
    run = PrintRun.objects.select_for_update().get(print_request=print_request)
    event = FulfillmentEvent(
        tenant=print_request.tenant,
        print_request=print_request,
        print_run=run,
        event_type=event_type,
        actor=actor,
        idempotency_key=idempotency_key,
        occurred_at=occurred_at or timezone.now(),
        reference=reference,
        notes=notes,
        metadata={"quantity": print_request.quantity},
    )
    event.full_clean()
    event.save()
    _transition_request(
        print_request=print_request,
        to_status=target,
        actor=actor,
        metadata={"fulfillment_event_id": event.pk, "reference": reference},
    )
    AuditEvent.objects.create(
        tenant=print_request.tenant,
        actor=actor,
        action=f"printing.{event_type}",
        object_type="PrintRequest",
        object_id=str(print_request.pk),
        metadata={
            "run_id": run.pk,
            "event_id": event.pk,
            "quantity": print_request.quantity,
            "reference": reference,
        },
    )
    return event, True


@transaction.atomic
def correct_fulfillment(*, event, actor, idempotency_key, reason, notes="", reference=""):
    if not reason.strip():
        raise ValidationError("A correction reason is required.")
    event = FulfillmentEvent.objects.select_for_update().get(pk=event.pk)
    existing = FulfillmentEvent.objects.filter(
        tenant=event.tenant,
        idempotency_key=idempotency_key,
    ).first()
    if existing:
        return existing, False
    if hasattr(event, "correction_event"):
        raise ValidationError("This fulfillment event already has a correction.")
    correction = FulfillmentEvent(
        tenant=event.tenant,
        print_request=event.print_request,
        print_run=event.print_run,
        physical_card=event.physical_card,
        event_type=FulfillmentEvent.Kind.CORRECTION,
        compensates=event,
        actor=actor,
        idempotency_key=idempotency_key,
        occurred_at=timezone.now(),
        reference=reference,
        notes=notes,
        reason=reason,
        metadata={"compensated_event_type": event.event_type},
    )
    correction.full_clean()
    correction.save()
    AuditEvent.objects.create(
        tenant=event.tenant,
        actor=actor,
        action="printing.fulfillment_corrected",
        object_type="FulfillmentEvent",
        object_id=str(event.pk),
        metadata={"correction_event_id": correction.pk, "reason": reason},
    )
    return correction, True


def legacy_reconciliation_preview(*, tenant, batch, start_number, end_number):
    if batch.tenant_id != tenant.pk:
        raise ValidationError("Legacy batch must belong to the selected tenant.")
    if start_number > end_number:
        raise ValidationError("Legacy range start cannot exceed its end.")
    cards = PhysicalCard.objects.filter(
        tenant=tenant,
        batch=batch,
        is_legacy=True,
        number__gte=start_number,
        number__lte=end_number,
    ).order_by("number")
    rows = list(cards.values("id", "number", "code", "status"))
    card_ids = [row["id"] for row in rows]
    existing = Counter(
        FulfillmentEvent.objects.filter(
            tenant=tenant,
            physical_card_id__in=card_ids,
            event_type__in=(
                FulfillmentEvent.Kind.PRINTED,
                FulfillmentEvent.Kind.DELIVERED,
            ),
        ).values_list("event_type", flat=True)
    )
    status_counts = Counter(row["status"] for row in rows)
    return {
        "tenant": tenant,
        "batch": batch,
        "start_number": start_number,
        "end_number": end_number,
        "cards": rows,
        "count": len(rows),
        "first_code": rows[0]["code"] if rows else "",
        "last_code": rows[-1]["code"] if rows else "",
        "status_counts": dict(status_counts),
        "existing_printed": existing[FulfillmentEvent.Kind.PRINTED],
        "existing_delivered": existing[FulfillmentEvent.Kind.DELIVERED],
    }


@transaction.atomic
def confirm_legacy_reconciliation(
    *,
    tenant,
    batch,
    start_number,
    end_number,
    expected_count,
    event_types,
    actor,
    occurred_at,
    reference,
    notes,
):
    event_types = tuple(dict.fromkeys(event_types))
    allowed = {FulfillmentEvent.Kind.PRINTED, FulfillmentEvent.Kind.DELIVERED}
    if not event_types or set(event_types) - allowed:
        raise ValidationError("Choose printed and/or delivered for legacy reconciliation.")
    preview = legacy_reconciliation_preview(
        tenant=tenant,
        batch=batch,
        start_number=start_number,
        end_number=end_number,
    )
    cards = list(
        PhysicalCard.objects.select_for_update()
        .filter(id__in=[row["id"] for row in preview["cards"]])
        .order_by("number")
    )
    if expected_count != len(cards) or expected_count != preview["count"]:
        raise ValidationError(
            "The confirmed card count no longer matches the dry-run preview."
        )
    if expected_count <= 0:
        raise ValidationError("The selected legacy range contains no cards.")
    created = []
    for card in cards:
        for event_type in event_types:
            event, was_created = FulfillmentEvent.objects.get_or_create(
                tenant=tenant,
                idempotency_key=f"legacy:{event_type}:physical-card:{card.pk}",
                defaults={
                    "physical_card": card,
                    "event_type": event_type,
                    "actor": actor,
                    "occurred_at": occurred_at,
                    "reference": reference,
                    "notes": notes,
                    "reason": "Legacy inventory reconciliation confirmed by platform operator.",
                    "metadata": {
                        "legacy": True,
                        "batch_id": batch.pk,
                        "range_start": start_number,
                        "range_end": end_number,
                    },
                },
            )
            if was_created:
                event.full_clean()
                created.append(event)
    AuditEvent.objects.create(
        tenant=tenant,
        actor=actor,
        action="printing.legacy_reconciled",
        object_type="CardBatch",
        object_id=str(batch.pk),
        metadata={
            "range_start": start_number,
            "range_end": end_number,
            "confirmed_count": expected_count,
            "event_types": list(event_types),
            "events_created": len(created),
            "occurred_at": occurred_at.isoformat(),
            "reference": reference,
        },
    )
    return created


__all__ = [
    "allocate_print_run",
    "approve_print_request",
    "cancel_print_request",
    "claim_next_print_job",
    "complete_print_job",
    "confirm_legacy_reconciliation",
    "correct_fulfillment",
    "fail_print_job",
    "generate_print_package",
    "legacy_reconciliation_preview",
    "process_next_print_job",
    "record_fulfillment",
    "reject_print_request",
    "resolve_package_path",
    "submit_print_request",
]
