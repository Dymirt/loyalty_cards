"""Public enrollment and authorized tenant follow-up HTTP adapters."""

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.http import FileResponse, Http404, HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from cards.models import PhysicalCard
from communications.services import customer_apple_pass
from dotykacka.models import AuditEvent
from tenants.authorization import (
    can_manage_integrations,
    get_public_tenant,
    tenant_for_card_code,
    tenant_for_verified_host,
)
from tenants.forms import TenantDomainRequestForm
from tenants.models import Tenant
from operations.rate_limits import rate_limit_response

from .forms import FollowUpActionForm, LoyaltyCustomerRegistrationForm, registration_form_data
from .jobs import EMAIL_JOB_KIND, enqueue_enrollment_followups
from .links import EnrollmentLinkError, EnrollmentLinkExpired, resolve_access_link
from .models import Enrollment, EnrollmentFollowUp
from .services import (
    registration_brand_for_tenant,
    register_customer_with_card,
    request_tenant_domain,
    resend_enrollment_email,
    retry_enrollment_followup,
)


def _render_registration(request, form, tenant, brand, *, tenant_slug=None, status=200):
    form_action = (
        reverse("enrollment:tenant_register", args=[tenant.slug])
        if tenant_slug
        else reverse("enrollment:register")
    )
    return render(
        request,
        "enrollment/register.html",
        {
            "form": form,
            "form_action": form_action,
            "tenant": tenant,
            "registration_brand": brand,
        },
        status=status,
    )


@require_http_methods(["GET", "POST"])
def register_customer_form(request, tenant_slug=None):
    if request.method == "POST":
        limited = rate_limit_response(
            request,
            scope="enrollment.register",
            limit=settings.ENROLLMENT_RATE_LIMIT,
            window_seconds=settings.PUBLIC_RATE_LIMIT_WINDOW_SECONDS,
            extra_identity=f"tenant:{tenant_slug or 'global'}",
        )
        if limited is not None:
            return limited
    hosted_tenant = (
        tenant_for_verified_host(request.get_host()) if tenant_slug is None else None
    )
    submitted_data = registration_form_data(request.POST) if request.method == "POST" else None
    inferred_tenant = (
        tenant_for_card_code(submitted_data.get("barcode"))
        if submitted_data is not None and tenant_slug is None and hosted_tenant is None
        else None
    )
    if tenant_slug is not None:
        fallback_tenant = get_public_tenant(tenant_slug)
    elif hosted_tenant is not None:
        fallback_tenant = hosted_tenant
    else:
        fallback_tenant = get_public_tenant()
    tenant = inferred_tenant or hosted_tenant or fallback_tenant
    brand = registration_brand_for_tenant(tenant)
    if request.method == "GET":
        return _render_registration(
            request,
            LoyaltyCustomerRegistrationForm(
                tenant=tenant,
                brand_snapshot=brand,
                initial={"tenant_confirmation": tenant.slug},
            ),
            tenant,
            brand,
            tenant_slug=tenant_slug,
        )
    form = LoyaltyCustomerRegistrationForm(
        submitted_data,
        tenant=tenant,
        brand_snapshot=brand,
    )
    if (
        inferred_tenant is not None
        and inferred_tenant.pk != fallback_tenant.pk
        and submitted_data.get("tenant_confirmation") != inferred_tenant.slug
    ):
        confirmation_data = submitted_data.copy()
        confirmation_data["tenant_confirmation"] = inferred_tenant.slug
        confirmation_data["marketing_consent"] = ""
        form = LoyaltyCustomerRegistrationForm(
            confirmation_data,
            tenant=inferred_tenant,
            brand_snapshot=brand,
        )
        form.add_error(
            None,
            _(
                "Rozpoznaliśmy program z kodu karty. Sprawdź markę i warunki zgody, "
                "a następnie potwierdź rejestrację."
            ),
        )
        return _render_registration(
            request,
            form,
            inferred_tenant,
            brand,
            status=409,
        )
    if not form.is_valid():
        return _render_registration(
            request,
            form,
            tenant,
            brand,
            tenant_slug=tenant_slug,
            status=400,
        )
    try:
        result = register_customer_with_card(tenant=tenant, cleaned_data=form.cleaned_data)
    except (IntegrityError, PhysicalCard.DoesNotExist, ValidationError) as exc:
        if isinstance(exc, ValidationError) and not isinstance(exc, IntegrityError):
            form.add_error(None, "; ".join(exc.messages))
        else:
            form.add_error("barcode", _("Ta karta już istnieje w bazie danych."))
        return _render_registration(
            request,
            form,
            tenant,
            brand,
            tenant_slug=tenant_slug,
            status=409,
        )
    messages.success(
        request, _("Zarejestrowano kartę. Integracje są realizowane w tle.")
    )
    return redirect("enrollment:public_status", token=result.access_token)


def _resolve_public_link_or_response(token):
    try:
        return resolve_access_link(token), None
    except EnrollmentLinkExpired:
        return None, HttpResponse(
            _("Ten bezpieczny link wygasł. Poproś firmę o ponowne wysłanie."),
            status=410,
        )
    except EnrollmentLinkError:
        raise Http404(_("Nieprawidłowy link rejestracji."))


def _public_status_context(link):
    enrollment = link.enrollment
    followups = list(
        enrollment.followups.select_related("integration_job").order_by(
            "kind", "generation"
        )
    )
    wallet = getattr(enrollment.customer, "wallet_pass", None)
    return {
        "tenant": enrollment.tenant,
        "registration_brand": enrollment.brand_snapshot,
        "enrollment": enrollment,
        "link": link,
        "followups": followups,
        "wallet": wallet,
        "google_save_url": (
            getattr(wallet, "google_save_url", "")
            or enrollment.customer.google_jwt_url
        ),
        "apple_ready": customer_apple_pass(
            enrollment.customer,
            create_identity=False,
        ).is_file(),
    }


@require_GET
def public_status(request, token):
    link, response = _resolve_public_link_or_response(token)
    if response:
        return response
    context = _public_status_context(link)
    context["access_token"] = token
    return render(request, "enrollment/public_status.html", context)


@require_GET
def public_apple_pass(request, token):
    link, response = _resolve_public_link_or_response(token)
    if response:
        return response
    path = customer_apple_pass(
        link.enrollment.customer,
        create_identity=False,
    )
    if not path.is_file():
        raise Http404(_("Karta Apple Wallet nie jest jeszcze gotowa."))
    return FileResponse(
        path.open("rb"),
        as_attachment=True,
        filename="loyalty-card.pkpass",
        content_type="application/vnd.apple.pkpass",
    )


def _tenant_or_forbidden(request, tenant_slug):
    tenant = get_object_or_404(
        Tenant.objects.select_related("brand"),
        slug=tenant_slug,
        is_active=True,
    )
    if not can_manage_integrations(request.user, tenant):
        return tenant, HttpResponseForbidden(
            _("Nie masz uprawnień do rejestracji tej firmy.")
        )
    return tenant, None


def _management_context(*, tenant, domain_form=None):
    return {
        "tenant": tenant,
        "enrollments": Enrollment.objects.filter(tenant=tenant)
        .select_related("customer", "physical_card", "consent_record")
        .prefetch_related("followups__integration_job")[:100],
        "domains": tenant.registration_domains.all(),
        "domain_form": domain_form or TenantDomainRequestForm(),
        "active_nav": "enrollments",
        "can_manage_integrations": True,
        "can_manage_card_designs": True,
        "can_manage_billing": True,
        "can_manage_printing": True,
        "can_manage_enrollments": True,
    }


@login_required
@require_GET
def tenant_enrollments(request, tenant_slug):
    tenant, forbidden = _tenant_or_forbidden(request, tenant_slug)
    if forbidden:
        return forbidden
    return render(
        request,
        "enrollment/tenant_enrollments.html",
        _management_context(tenant=tenant),
    )


def _detail_context(enrollment):
    return {
        "tenant": enrollment.tenant,
        "enrollment": enrollment,
        "followups": enrollment.followups.select_related(
            "integration_job", "integration_job__communication_delivery"
        ),
        "consent_history": enrollment.customer.consent_records.all(),
        "retry_form": FollowUpActionForm(action="retry"),
        "resend_form": FollowUpActionForm(action="resend"),
        "ensure_form": FollowUpActionForm(action="ensure"),
        "email_job_kind": EMAIL_JOB_KIND,
        "active_nav": "enrollments",
        "can_manage_integrations": True,
        "can_manage_card_designs": True,
        "can_manage_billing": True,
        "can_manage_printing": True,
        "can_manage_enrollments": True,
    }


@login_required
@require_GET
def enrollment_detail(request, tenant_slug, enrollment_id):
    tenant, forbidden = _tenant_or_forbidden(request, tenant_slug)
    if forbidden:
        return forbidden
    enrollment = get_object_or_404(
        Enrollment.objects.select_related(
            "tenant", "customer", "physical_card", "consent_record"
        ),
        pk=enrollment_id,
        tenant=tenant,
    )
    return render(request, "enrollment/detail.html", _detail_context(enrollment))


def _followup_partial(request, enrollment):
    enrollment = Enrollment.objects.select_related(
        "tenant", "customer", "physical_card", "consent_record"
    ).get(pk=enrollment.pk)
    return render(
        request,
        "enrollment/partials/followups.html",
        _detail_context(enrollment),
    )


@login_required
@require_POST
def retry_followup(request, tenant_slug, followup_id):
    tenant, forbidden = _tenant_or_forbidden(request, tenant_slug)
    if forbidden:
        return forbidden
    followup = get_object_or_404(
        EnrollmentFollowUp.objects.select_related("enrollment", "integration_job"),
        pk=followup_id,
        enrollment__tenant=tenant,
    )
    form = FollowUpActionForm(request.POST, action="retry")
    if form.is_valid():
        try:
            _job, created = retry_enrollment_followup(
                followup=followup,
                actor=request.user,
                **form.cleaned_data,
            )
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
        else:
            messages.success(
                request,
                _("Zaplanowano ponowną próbę.")
                if created
                else _("Ta próba została już zaplanowana."),
            )
    if request.headers.get("HX-Request") == "true":
        return _followup_partial(request, followup.enrollment)
    return redirect(
        "enrollment:detail",
        tenant_slug=tenant.slug,
        enrollment_id=followup.enrollment_id,
    )


@login_required
@require_POST
def resend_email(request, tenant_slug, enrollment_id):
    tenant, forbidden = _tenant_or_forbidden(request, tenant_slug)
    if forbidden:
        return forbidden
    enrollment = get_object_or_404(Enrollment, pk=enrollment_id, tenant=tenant)
    form = FollowUpActionForm(request.POST, action="resend")
    if form.is_valid():
        try:
            _followup, created = resend_enrollment_email(
                enrollment=enrollment,
                actor=request.user,
                **form.cleaned_data,
            )
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
        else:
            messages.success(
                request,
                _("Utworzono nowe, jawnie zlecone wysłanie wiadomości.")
                if created
                else _("To wysłanie zostało już zlecone."),
            )
    if request.headers.get("HX-Request") == "true":
        return _followup_partial(request, enrollment)
    return redirect(
        "enrollment:detail",
        tenant_slug=tenant.slug,
        enrollment_id=enrollment.pk,
    )


@login_required
@require_POST
def ensure_followups(request, tenant_slug, enrollment_id):
    tenant, forbidden = _tenant_or_forbidden(request, tenant_slug)
    if forbidden:
        return forbidden
    enrollment = get_object_or_404(Enrollment, pk=enrollment_id, tenant=tenant)
    form = FollowUpActionForm(request.POST, action="ensure")
    if form.is_valid():
        jobs = enqueue_enrollment_followups(enrollment.pk)
        AuditEvent.objects.create(
            tenant=tenant,
            actor=request.user,
            action="enrollment.followups_ensured",
            object_type="Enrollment",
            object_id=str(enrollment.pk),
            metadata={"job_count": len(jobs)},
        )
        messages.success(request, _("Sprawdzono i dopisano brakujące zadania."))
    if request.headers.get("HX-Request") == "true":
        return _followup_partial(request, enrollment)
    return redirect(
        "enrollment:detail",
        tenant_slug=tenant.slug,
        enrollment_id=enrollment.pk,
    )


@login_required
@require_POST
def request_domain(request, tenant_slug):
    tenant, forbidden = _tenant_or_forbidden(request, tenant_slug)
    if forbidden:
        return forbidden
    form = TenantDomainRequestForm(request.POST)
    if form.is_valid():
        try:
            _domain, created = request_tenant_domain(
                tenant=tenant,
                actor=request.user,
                hostname=form.cleaned_data["hostname"],
            )
        except ValidationError as exc:
            form.add_error("hostname", exc)
        else:
            messages.success(
                request,
                _("Zgłoszono domenę do weryfikacji operatora.")
                if created
                else _("Ta domena jest już zgłoszona."),
            )
            return redirect("enrollment:manage", tenant_slug=tenant.slug)
    return render(
        request,
        "enrollment/tenant_enrollments.html",
        _management_context(tenant=tenant, domain_form=form),
        status=400,
    )


__all__ = [
    "enrollment_detail",
    "ensure_followups",
    "public_apple_pass",
    "public_status",
    "register_customer_form",
    "request_domain",
    "resend_email",
    "retry_followup",
    "tenant_enrollments",
]
