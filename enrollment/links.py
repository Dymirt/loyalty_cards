"""Signed, database-expiring links for customer enrollment status and Wallet files."""

from datetime import timedelta
from uuid import UUID

from django.conf import settings
from django.core import signing
from django.urls import reverse
from django.utils import timezone

from communications.registry import EmailApplicationContext
from integrations.contracts import IntegrationError
from tenants.models import TenantDomain

from .models import EnrollmentAccessLink


LINK_SALT = "loyalty.enrollment.access.v1"


class EnrollmentLinkError(ValueError):
    pass


class EnrollmentLinkExpired(EnrollmentLinkError):
    pass


def issue_access_link(*, enrollment, reason, actor=None, now=None):
    now = now or timezone.now()
    link = EnrollmentAccessLink(
        enrollment=enrollment,
        reason=reason,
        created_by=actor,
        expires_at=now + timedelta(days=settings.ENROLLMENT_LINK_TTL_DAYS),
    )
    link.full_clean()
    link.save()
    return link


def token_for_link(link):
    return signing.Signer(salt=LINK_SALT).sign(str(link.public_id))


def url_for_link(link):
    domain = (
        link.enrollment.tenant.registration_domains.filter(
            status=TenantDomain.Status.VERIFIED,
        )
        .order_by("-is_primary", "pk")
        .first()
    )
    base_url = f"https://{domain.hostname}" if domain else settings.APP_BASE_URL
    return base_url + reverse(
        "enrollment:public_status",
        args=[token_for_link(link)],
    )


def resolve_access_link(token, *, now=None):
    try:
        value = signing.Signer(salt=LINK_SALT).unsign(token)
        public_id = UUID(value)
    except (signing.BadSignature, ValueError) as exc:
        raise EnrollmentLinkError("Invalid enrollment access link.") from exc
    try:
        link = EnrollmentAccessLink.objects.select_related(
            "enrollment__tenant__brand",
            "enrollment__customer",
            "enrollment__physical_card",
        ).get(public_id=public_id)
    except EnrollmentAccessLink.DoesNotExist as exc:
        raise EnrollmentLinkError("Invalid enrollment access link.") from exc
    if link.expires_at <= (now or timezone.now()):
        raise EnrollmentLinkExpired("Enrollment access link has expired.")
    return link


def email_application_context_for_job(job):
    link_id = job.payload.get("enrollment_link_id")
    if not link_id:
        return EmailApplicationContext()
    try:
        link = EnrollmentAccessLink.objects.select_related("enrollment").get(pk=link_id)
    except EnrollmentAccessLink.DoesNotExist as exc:
        raise IntegrationError(error_code="enrollment_link_missing") from exc
    if link.expires_at <= timezone.now():
        raise IntegrationError(error_code="enrollment_link_expired")
    try:
        generation = job.enrollment_followup.generation
    except AttributeError:
        generation = 1
    return EmailApplicationContext(
        application_link_url=url_for_link(link),
        brand_snapshot=link.enrollment.brand_snapshot,
        generation=generation,
    )


__all__ = [
    "EnrollmentLinkError",
    "EnrollmentLinkExpired",
    "email_application_context_for_job",
    "issue_access_link",
    "resolve_access_link",
    "token_for_link",
    "url_for_link",
]
