"""Transactional enrollment and authorized follow-up orchestration."""

from dataclasses import dataclass
from functools import partial
import hashlib
import json
from uuid import uuid4

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max
from django.utils.translation import gettext as _

from billing.services import record_card_issuance
from cards.services import assign_locked_card, lock_available_card
from customers.services import create_customer, record_marketing_consent
from dotykacka.models import AuditEvent
from integrations.models import IntegrationConnection
from integrations.models import IntegrationJob
from integrations.services import enqueue_job, retry_failed_job
from tenants.models import Tenant, TenantDomain
from wallets.services import wallet_identity

from .links import issue_access_link, token_for_link
from .models import (
    Enrollment,
    EnrollmentAccessLink,
    EnrollmentEvent,
    EnrollmentFollowUp,
    VirtualCardApplication,
    VirtualCardFollowUp,
)


EMAIL_JOB_KIND = "communications.email.pass"


@dataclass(frozen=True)
class EnrollmentResult:
    customer: object
    enrollment: Enrollment
    access_link: EnrollmentAccessLink
    access_token: str


@dataclass(frozen=True)
class VirtualCardResult:
    application: VirtualCardApplication
    created: bool


class VirtualCardIdempotencyConflict(ValidationError):
    pass


def published_brand_release(tenant):
    design = (
        tenant.card_designs
        .filter(is_virtual_catalog=False)
        .select_related("brand_revision")
        .order_by("-version", "-pk")
        .first()
    )
    revision = design.brand_revision if design else tenant.brand_revisions.first()
    live_brand = tenant.brand
    source = revision or live_brand
    fields = (
        "public_name",
        "tagline",
        "address",
        "phone",
        "email",
        "website_url",
        "email_subject",
        "email_signature",
        "marketing_consent_text",
    )
    snapshot = {name: getattr(source, name, "") for name in fields}
    snapshot.update(
        {
            "tenant_id": tenant.pk,
            "tenant_slug": tenant.slug,
            "brand_revision_id": getattr(revision, "pk", None),
            "brand_revision_version": getattr(revision, "version", None),
            "brand_checksum": getattr(revision, "snapshot_checksum", ""),
            "card_design_id": getattr(design, "pk", None),
            "card_design_version": getattr(design, "version", None),
            "card_design_checksum": getattr(design, "design_checksum", ""),
            "logo_path": (
                design.logo.name
                if design and design.logo
                else live_brand.logo_path
            ),
            "background_image_path": (
                live_brand.background_image_path
            ),
        }
    )
    return revision, design, snapshot


def registration_brand_for_tenant(tenant):
    return published_brand_release(tenant)[2]


def brand_snapshot_for_design(tenant, design):
    revision = design.brand_revision
    fields = (
        "public_name",
        "tagline",
        "address",
        "phone",
        "email",
        "website_url",
        "email_subject",
        "email_signature",
        "marketing_consent_text",
    )
    snapshot = {name: getattr(revision, name, "") for name in fields}
    snapshot.update(
        {
            "tenant_id": tenant.pk,
            "tenant_slug": tenant.slug,
            "brand_revision_id": revision.pk,
            "brand_revision_version": revision.version,
            "brand_checksum": revision.snapshot_checksum,
            "card_design_id": design.pk,
            "card_design_version": design.version,
            "card_design_checksum": design.design_checksum,
            "card_design_logo": bool(design.logo),
            "logo_path": design.logo.name if design.logo else tenant.brand.logo_path,
            "background_image_path": (
                design.background_source.name
                if design.background_source
                else tenant.brand.background_image_path
            ),
        }
    )
    return snapshot


def virtual_wallet_availability(tenant):
    apple_enabled = bool(
        settings.APPLE_WALLET_PASS_TYPE_IDENTIFIER
        and settings.APPLE_WALLET_TEAM_IDENTIFIER
    )
    google_connection = IntegrationConnection.objects.filter(
        tenant=tenant,
        provider=IntegrationConnection.Provider.GOOGLE_WALLET,
        enabled=True,
    ).first()
    return apple_enabled, google_connection


def virtual_card_request_checksum(cleaned_data):
    payload = {
        "first_name": cleaned_data["first_name"],
        "last_name": cleaned_data["last_name"],
        "email": cleaned_data["email"].lower(),
        "phone": cleaned_data["phone"],
        "card_design_id": cleaned_data["card_design_id"],
        "marketing_consent": True,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def enqueue_virtual_card_followups(application):
    apple_enabled, google_connection = virtual_wallet_availability(application.tenant)
    specs = []
    if apple_enabled:
        specs.append(("wallet.apple.issue", None))
    if google_connection is not None:
        specs.append(("wallet.google.issue", google_connection))
    if specs:
        specs.append((EMAIL_JOB_KIND, None))
    jobs = []
    for kind, connection in specs:
        job = enqueue_job(
            tenant=application.tenant,
            connection=connection,
            kind=kind,
            idempotency_key=f"virtual-card:{application.public_id}:{kind}:v1",
            payload={
                "customer_id": application.customer_id,
                "virtual_card_application_id": application.pk,
            },
        )
        followup, _created = VirtualCardFollowUp.objects.get_or_create(
            application=application,
            kind=kind,
            defaults={"integration_job": job},
        )
        if followup.integration_job_id != job.pk:
            raise ValueError("Virtual-card follow-up key was reused with different inputs.")
        jobs.append(job)
    return jobs


@transaction.atomic
def register_virtual_card(
    *,
    tenant,
    card_design,
    cleaned_data,
    idempotency_key,
    request_sha256,
    source,
    api_key=None,
):
    tenant = Tenant.objects.select_for_update().select_related("brand").get(pk=tenant.pk)
    if api_key is not None:
        api_key = type(api_key).objects.select_for_update().get(pk=api_key.pk)
        if not api_key.is_active or api_key.tenant_id != tenant.pk:
            raise ValidationError(_("Klucz API nie jest aktywny dla tej firmy."))
    existing = VirtualCardApplication.objects.filter(
        tenant=tenant,
        idempotency_key=idempotency_key,
    ).first()
    if existing is not None:
        if existing.request_sha256 != request_sha256:
            raise VirtualCardIdempotencyConflict(
                _("Ten klucz idempotencji został wcześniej użyty z innymi danymi.")
            )
        enqueue_virtual_card_followups(existing)
        return VirtualCardResult(application=existing, created=False)
    card_design = tenant.card_designs.select_related("brand_revision").get(
        pk=card_design.pk,
    )
    apple_enabled, google_connection = virtual_wallet_availability(tenant)
    if not apple_enabled and google_connection is None:
        raise ValidationError(_("Ta firma nie ma aktywnego wydawcy kart Wallet."))
    public_id = uuid4()
    card_code = f"{tenant.card_prefix}-V-{public_id.hex[:16].upper()}"
    customer = create_customer(
        tenant=tenant,
        card_code=card_code,
        first_name=cleaned_data["first_name"],
        last_name=cleaned_data["last_name"],
        email=cleaned_data["email"],
        phone=cleaned_data["phone"],
    )
    usage_result = record_card_issuance(
        tenant=tenant,
        card_identity=public_id,
        physical=False,
        metadata={"source": source, "card_design_id": card_design.pk},
    )
    revision = card_design.brand_revision
    consent_text = revision.marketing_consent_text or tenant.brand.marketing_consent_text
    consent = record_marketing_consent(
        customer=customer,
        consent_text=consent_text or "Marketing consent",
        source=source,
        policy_version=f"brand:{revision.version}:{revision.snapshot_checksum[:16]}",
        metadata={
            "brand_revision_id": revision.pk,
            "card_design_id": card_design.pk,
            "virtual_card": True,
        },
    )
    wallet_identity(customer, card_design=card_design)
    application = VirtualCardApplication(
        tenant=tenant,
        api_key=api_key,
        customer=customer,
        card_design=card_design,
        consent_record=consent,
        usage_event=usage_result.event,
        public_id=public_id,
        idempotency_key=idempotency_key,
        request_sha256=request_sha256,
        source=source,
        brand_snapshot=brand_snapshot_for_design(tenant, card_design),
    )
    application.full_clean()
    application.save()
    jobs = enqueue_virtual_card_followups(application)
    AuditEvent.objects.create(
        tenant=tenant,
        actor=None,
        action="virtual_card.application_created",
        object_type="VirtualCardApplication",
        object_id=str(application.pk),
        metadata={
            "public_id": str(application.public_id),
            "card_design_id": card_design.pk,
            "api_key_id": getattr(api_key, "pk", None),
            "job_count": len(jobs),
            "source": source,
        },
    )
    return VirtualCardResult(application=application, created=True)


def virtual_card_application_state(application):
    statuses = list(
        application.followups.values_list("kind", "integration_job__status")
    )
    if not statuses:
        return "queued"
    if any(status == IntegrationJob.Status.FAILED for _kind, status in statuses):
        return "failed"
    email_status = next(
        (status for kind, status in statuses if kind == EMAIL_JOB_KIND),
        None,
    )
    if email_status == IntegrationJob.Status.SUCCEEDED:
        return "email_sent"
    return "processing"


def _append_event(
    *,
    enrollment,
    kind,
    idempotency_key,
    actor=None,
    integration_job=None,
    reason="",
    metadata=None,
):
    event = EnrollmentEvent(
        enrollment=enrollment,
        kind=kind,
        idempotency_key=idempotency_key,
        actor=actor,
        integration_job=integration_job,
        reason=reason,
        metadata=metadata or {},
    )
    event.full_clean()
    event.save()
    return event


@transaction.atomic
def register_customer_with_card(*, tenant, cleaned_data):
    tenant = Tenant.objects.select_for_update().select_related("brand").get(pk=tenant.pk)
    revision, design, brand_snapshot = published_brand_release(tenant)
    card = lock_available_card(tenant=tenant, code=cleaned_data["barcode"])
    customer = create_customer(
        tenant=tenant,
        card_code=cleaned_data["barcode"],
        first_name=cleaned_data["first_name"],
        last_name=cleaned_data["last_name"],
        email=cleaned_data["email"],
        phone=cleaned_data["phone"],
    )
    assign_locked_card(card=card, customer=customer)
    usage_result = record_card_issuance(
        tenant=tenant,
        card_identity=card.pk,
        physical=True,
        metadata={"source": "public_registration"},
    )
    consent_text = brand_snapshot.get("marketing_consent_text") or "Marketing consent"
    policy_version = (
        f"brand:{revision.version}:{revision.snapshot_checksum[:16]}"
        if revision
        else "live-brand"
    )
    consent = record_marketing_consent(
        customer=customer,
        consent_text=consent_text,
        policy_version=policy_version,
        metadata={
            "brand_revision_id": getattr(revision, "pk", None),
            "card_design_id": getattr(design, "pk", None),
        },
    )
    enrollment = Enrollment(
        tenant=tenant,
        customer=customer,
        physical_card=card,
        consent_record=consent,
        usage_event=usage_result.event,
        brand_revision=revision,
        card_design=design,
        registration_key=f"physical-card:{card.pk}",
        brand_snapshot=brand_snapshot,
        consent_snapshot={
            "record_id": consent.pk,
            "purpose": consent.purpose,
            "policy_version": consent.policy_version,
            "text_sha256": consent.consent_text_sha256,
            "granted": consent.granted,
        },
    )
    enrollment.full_clean()
    enrollment.save()
    _append_event(
        enrollment=enrollment,
        kind=EnrollmentEvent.Kind.REGISTERED,
        idempotency_key="registration-committed",
        metadata={"source": enrollment.source},
    )
    _append_event(
        enrollment=enrollment,
        kind=EnrollmentEvent.Kind.CARD_ASSIGNED,
        idempotency_key="card-assigned",
        metadata={"physical_card_id": card.pk},
    )
    _append_event(
        enrollment=enrollment,
        kind=EnrollmentEvent.Kind.CONSENT_RECORDED,
        idempotency_key="consent-recorded",
        metadata={"consent_record_id": consent.pk},
    )
    _append_event(
        enrollment=enrollment,
        kind=EnrollmentEvent.Kind.ISSUANCE_RECORDED,
        idempotency_key="issuance-recorded",
        metadata={
            "managed_billing": usage_result.managed,
            "usage_event_id": getattr(usage_result.event, "pk", None),
        },
    )
    link = issue_access_link(
        enrollment=enrollment,
        reason=EnrollmentAccessLink.Reason.REGISTRATION,
    )
    AuditEvent.objects.create(
        tenant=tenant,
        actor=None,
        action="enrollment.registered",
        object_type="Enrollment",
        object_id=str(enrollment.pk),
        metadata={
            "physical_card_id": card.pk,
            "consent_record_id": consent.pk,
            "managed_billing": usage_result.managed,
            "brand_revision_id": getattr(revision, "pk", None),
        },
    )
    from .jobs import enqueue_enrollment_followups

    transaction.on_commit(
        partial(enqueue_enrollment_followups, enrollment.pk),
        robust=True,
    )
    return EnrollmentResult(
        customer=customer,
        enrollment=enrollment,
        access_link=link,
        access_token=token_for_link(link),
    )


@transaction.atomic
def retry_enrollment_followup(*, followup, actor, idempotency_key, reason):
    followup = (
        EnrollmentFollowUp.objects.select_for_update()
        .select_related("enrollment__tenant", "integration_job")
        .get(pk=followup.pk)
    )
    existing = EnrollmentEvent.objects.filter(
        enrollment=followup.enrollment,
        idempotency_key=idempotency_key,
    ).first()
    if existing:
        return followup.integration_job, False
    if followup.kind == EMAIL_JOB_KIND:
        raise ValidationError(_("E-mail o niepewnym wyniku wymaga jawnego ponownego wysłania."))
    try:
        job = retry_failed_job(job=followup.integration_job)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
    _append_event(
        enrollment=followup.enrollment,
        kind=EnrollmentEvent.Kind.RETRY_REQUESTED,
        idempotency_key=idempotency_key,
        actor=actor,
        integration_job=job,
        reason=reason,
        metadata={"followup_id": followup.pk, "prior_error_code": job.last_error_code},
    )
    AuditEvent.objects.create(
        tenant=followup.enrollment.tenant,
        actor=actor,
        action="enrollment.followup_retried",
        object_type="IntegrationJob",
        object_id=str(job.pk),
        metadata={"enrollment_id": followup.enrollment_id, "kind": job.kind},
    )
    return job, True


@transaction.atomic
def resend_enrollment_email(*, enrollment, actor, idempotency_key, reason):
    enrollment = (
        Enrollment.objects.select_for_update()
        .select_related("tenant", "customer")
        .get(pk=enrollment.pk)
    )
    existing = EnrollmentEvent.objects.filter(
        enrollment=enrollment,
        idempotency_key=idempotency_key,
    ).first()
    if existing:
        followup = EnrollmentFollowUp.objects.get(pk=existing.metadata["followup_id"])
        return followup, False
    if not enrollment.customer.email:
        raise ValidationError(_("Klient nie ma adresu e-mail."))
    generation = (
        EnrollmentFollowUp.objects.filter(enrollment=enrollment, kind=EMAIL_JOB_KIND)
        .aggregate(value=Max("generation"))["value"]
        or 0
    ) + 1
    link = issue_access_link(
        enrollment=enrollment,
        reason=EnrollmentAccessLink.Reason.RESEND,
        actor=actor,
    )
    job = enqueue_job(
        tenant=enrollment.tenant,
        kind=EMAIL_JOB_KIND,
        idempotency_key=(
            f"enrollment:{enrollment.customer_id}:{EMAIL_JOB_KIND}:resend:{idempotency_key}"
        ),
        payload={
            "customer_id": enrollment.customer_id,
            "enrollment_link_id": link.pk,
        },
    )
    followup = EnrollmentFollowUp(
        enrollment=enrollment,
        integration_job=job,
        kind=EMAIL_JOB_KIND,
        generation=generation,
        operation=EnrollmentFollowUp.Operation.RESEND,
        requested_by=actor,
    )
    followup.full_clean()
    followup.save()
    _append_event(
        enrollment=enrollment,
        kind=EnrollmentEvent.Kind.RESEND_REQUESTED,
        idempotency_key=idempotency_key,
        actor=actor,
        integration_job=job,
        reason=reason,
        metadata={"followup_id": followup.pk, "generation": generation, "link_id": link.pk},
    )
    AuditEvent.objects.create(
        tenant=enrollment.tenant,
        actor=actor,
        action="enrollment.email_resent",
        object_type="Enrollment",
        object_id=str(enrollment.pk),
        metadata={"job_id": job.pk, "generation": generation},
    )
    return followup, True


@transaction.atomic
def request_tenant_domain(*, tenant, actor, hostname):
    tenant = Tenant.objects.select_for_update().get(pk=tenant.pk)
    normalized = (hostname or "").strip().lower().rstrip(".")
    existing = TenantDomain.objects.filter(hostname=normalized).first()
    if existing:
        if existing.tenant_id != tenant.pk:
            raise ValidationError(_("Ta nazwa hosta jest już przypisana do innej firmy."))
        return existing, False
    domain = TenantDomain(
        tenant=tenant,
        hostname=normalized,
        created_by=actor,
    )
    domain.full_clean()
    domain.save()
    AuditEvent.objects.create(
        tenant=tenant,
        actor=actor,
        action="enrollment.domain_requested",
        object_type="TenantDomain",
        object_id=str(domain.pk),
        metadata={"hostname": domain.hostname},
    )
    return domain, True


__all__ = [
    "EnrollmentResult",
    "VirtualCardIdempotencyConflict",
    "VirtualCardResult",
    "brand_snapshot_for_design",
    "enqueue_virtual_card_followups",
    "published_brand_release",
    "registration_brand_for_tenant",
    "register_customer_with_card",
    "register_virtual_card",
    "request_tenant_domain",
    "resend_enrollment_email",
    "retry_enrollment_followup",
    "virtual_card_application_state",
    "virtual_card_request_checksum",
    "virtual_wallet_availability",
]
