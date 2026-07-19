"""Transactional enrollment and authorized follow-up orchestration."""

from dataclasses import dataclass
from functools import partial

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max

from billing.services import record_card_issuance
from cards.services import assign_locked_card, lock_available_card
from customers.services import create_customer, record_marketing_consent
from dotykacka.models import AuditEvent
from integrations.models import IntegrationJob
from integrations.services import enqueue_job, retry_failed_job
from tenants.models import Tenant, TenantDomain

from .links import issue_access_link, token_for_link
from .models import Enrollment, EnrollmentAccessLink, EnrollmentEvent, EnrollmentFollowUp


EMAIL_JOB_KIND = "communications.email.pass"


@dataclass(frozen=True)
class EnrollmentResult:
    customer: object
    enrollment: Enrollment
    access_link: EnrollmentAccessLink
    access_token: str


def published_brand_release(tenant):
    design = (
        tenant.card_designs
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
                design.background_source.name
                if design and design.background_source
                else live_brand.background_image_path
            ),
        }
    )
    return revision, design, snapshot


def registration_brand_for_tenant(tenant):
    return published_brand_release(tenant)[2]


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
        raise ValidationError("Email with an uncertain outcome requires explicit resend.")
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
        raise ValidationError("The customer does not have an email address.")
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
            raise ValidationError("This hostname is already assigned to another tenant.")
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
    "published_brand_release",
    "registration_brand_for_tenant",
    "register_customer_with_card",
    "request_tenant_domain",
    "resend_enrollment_email",
    "retry_enrollment_followup",
]
