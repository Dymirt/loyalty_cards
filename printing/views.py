"""Tenant and platform HTTP adapters for centralized printing."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import FileResponse, Http404, HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.http import require_GET, require_POST

from cards.services import tenant_inventory_queryset
from tenants.authorization import can_manage_billing, superuser_required
from tenants.models import Tenant
from dotykacka.models import AuditEvent

from .forms import (
    CorrectionForm,
    FulfillmentForm,
    LegacyConfirmForm,
    LegacyPreviewForm,
    OperatorReasonForm,
    PlatformQueueFilterForm,
    PrintRequestForm,
    RequiredReasonForm,
)
from .models import FulfillmentEvent, PrintPackage, PrintRequest, PrintRun
from .services import (
    allocate_print_run,
    approve_print_request,
    cancel_print_request,
    confirm_legacy_reconciliation,
    correct_fulfillment,
    legacy_reconciliation_preview,
    record_fulfillment,
    reject_print_request,
    resolve_package_path,
    submit_print_request,
)


def _tenant_or_forbidden(request, tenant_slug):
    tenant = get_object_or_404(
        Tenant.objects.select_related("brand"),
        slug=tenant_slug,
        is_active=True,
    )
    if not can_manage_billing(request.user, tenant):
        return tenant, HttpResponseForbidden(
            _("Nie masz uprawnień do zamówień druku tej firmy.")
        )
    return tenant, None


def _tenant_context(*, tenant, form=None):
    return {
        "tenant": tenant,
        "active_nav": "printing",
        "can_manage_billing": True,
        "can_manage_integrations": True,
        "can_manage_card_designs": True,
        "can_manage_printing": True,
        "print_form": form or PrintRequestForm(tenant=tenant),
        "print_requests": PrintRequest.objects.filter(tenant=tenant)
        .select_related("design", "quote")
        .prefetch_related("status_events", "fulfillment_events")[:30],
    }


@login_required
@require_GET
def tenant_printing(request, tenant_slug):
    tenant, forbidden = _tenant_or_forbidden(request, tenant_slug)
    if forbidden:
        return forbidden
    return render(request, "printing/tenant_printing.html", _tenant_context(tenant=tenant))


@login_required
@require_POST
def submit_request(request, tenant_slug):
    tenant, forbidden = _tenant_or_forbidden(request, tenant_slug)
    if forbidden:
        return forbidden
    form = PrintRequestForm(request.POST, tenant=tenant)
    if form.is_valid():
        try:
            print_request, created = submit_print_request(
                tenant=tenant,
                requested_by=request.user,
                **form.cleaned_data,
            )
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(
                request,
                _("Przekazano zamówienie do centrum druku.")
                if created
                else _("To zamówienie zostało już wcześniej przekazane."),
            )
            target = reverse("printing:tenant", args=[tenant.slug])
            if request.headers.get("HX-Request") == "true":
                response = HttpResponse(status=204)
                response["HX-Redirect"] = target
                return response
            return redirect(target)
    return render(
        request,
        "printing/tenant_printing.html",
        _tenant_context(tenant=tenant, form=form),
        status=400,
    )


def _platform_context(*, filter_data=None, legacy_preview=None, legacy_confirm_form=None):
    queue_filter_form = PlatformQueueFilterForm(filter_data)
    requests = (
        PrintRequest.objects.select_related(
            "tenant",
            "design",
            "quote",
            "requested_by",
        )
        .prefetch_related("status_events")
    )
    if queue_filter_form.is_valid():
        if queue_filter_form.cleaned_data.get("tenant"):
            requests = requests.filter(tenant=queue_filter_form.cleaned_data["tenant"])
        if queue_filter_form.cleaned_data.get("status"):
            requests = requests.filter(status=queue_filter_form.cleaned_data["status"])
    requests = requests.all()[:100]
    return {
        "print_requests": requests,
        "queue_filter_form": queue_filter_form,
        "status_counts": {
            status: PrintRequest.objects.filter(status=status).count()
            for status, _label in PrintRequest.Status.choices
        },
        "tenants": tenant_inventory_queryset(Tenant),
        "legacy_preview_form": LegacyPreviewForm(),
        "legacy_preview": legacy_preview,
        "legacy_confirm_form": legacy_confirm_form,
        "platform_nav": "print_center",
    }


@superuser_required
@require_GET
def platform_print_center(request):
    return render(
        request,
        "printing/platform_print_center.html",
        _platform_context(filter_data=request.GET or None),
    )


@superuser_required
@require_GET
def platform_request_detail(request, request_id):
    print_request = get_object_or_404(
        PrintRequest.objects.select_related(
            "tenant",
            "design",
            "quote",
            "proof_front",
            "proof_back",
            "requested_by",
        ).prefetch_related(
            "status_events",
            "fulfillment_events__actor",
        ),
        pk=request_id,
    )
    try:
        run = PrintRun.objects.select_related("batch").prefetch_related("jobs").get(
            print_request=print_request
        )
    except PrintRun.DoesNotExist:
        run = None
    return render(
        request,
        "printing/platform_request_detail.html",
        {
            "print_request": print_request,
            "run": run,
            "approve_form": OperatorReasonForm(),
            "reject_form": RequiredReasonForm(),
            "cancel_form": RequiredReasonForm(),
            "fulfillment_form": FulfillmentForm(
                current_status=print_request.status
            ),
            "correction_form": CorrectionForm(),
        },
    )


def _platform_action_response(request, print_request, success_text):
    messages.success(request, success_text)
    return redirect("printing:platform_detail", request_id=print_request.pk)


@superuser_required
@require_POST
def approve_request(request, request_id):
    print_request = get_object_or_404(PrintRequest, pk=request_id)
    form = OperatorReasonForm(request.POST)
    if form.is_valid():
        try:
            approve_print_request(
                print_request=print_request,
                actor=request.user,
                reason=form.cleaned_data["reason"],
            )
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
        else:
            return _platform_action_response(
                request, print_request, _("Zatwierdzono zamówienie.")
            )
    return redirect("printing:platform_detail", request_id=print_request.pk)


@superuser_required
@require_POST
def reject_request(request, request_id):
    print_request = get_object_or_404(PrintRequest, pk=request_id)
    form = RequiredReasonForm(request.POST)
    if form.is_valid():
        try:
            reject_print_request(
                print_request=print_request,
                actor=request.user,
                reason=form.cleaned_data["reason"],
            )
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
        else:
            return _platform_action_response(
                request, print_request, _("Odrzucono zamówienie.")
            )
    else:
        messages.error(request, _("Podaj powód odrzucenia."))
    return redirect("printing:platform_detail", request_id=print_request.pk)


@superuser_required
@require_POST
def allocate_request(request, request_id):
    print_request = get_object_or_404(PrintRequest, pk=request_id)
    try:
        _run, created = allocate_print_run(
            print_request=print_request,
            actor=request.user,
        )
    except ValidationError as exc:
        messages.error(request, "; ".join(exc.messages))
    else:
        messages.success(
            request,
            _("Przydzielono numery i dodano zadanie produkcyjne.")
            if created
            else _("Numery były już przydzielone."),
        )
    return redirect("printing:platform_detail", request_id=print_request.pk)


@superuser_required
@require_POST
def cancel_request(request, request_id):
    print_request = get_object_or_404(PrintRequest, pk=request_id)
    form = RequiredReasonForm(request.POST)
    if form.is_valid():
        try:
            cancel_print_request(
                print_request=print_request,
                actor=request.user,
                reason=form.cleaned_data["reason"],
            )
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
        else:
            messages.success(
                request, _("Anulowano zamówienie bez ponownego użycia numerów.")
            )
    else:
        messages.error(request, _("Podaj powód anulowania."))
    return redirect("printing:platform_detail", request_id=print_request.pk)


@superuser_required
@require_POST
def fulfill_request(request, request_id):
    print_request = get_object_or_404(PrintRequest, pk=request_id)
    form = FulfillmentForm(request.POST, current_status=print_request.status)
    if form.is_valid():
        try:
            record_fulfillment(
                print_request=print_request,
                actor=request.user,
                **form.cleaned_data,
            )
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
        else:
            messages.success(request, _("Dopisano etap realizacji."))
    else:
        messages.error(request, _("Nieprawidłowy etap realizacji."))
    return redirect("printing:platform_detail", request_id=print_request.pk)


@superuser_required
@require_POST
def correct_event(request, event_id):
    event = get_object_or_404(FulfillmentEvent, pk=event_id)
    form = CorrectionForm(request.POST)
    if form.is_valid():
        try:
            correct_fulfillment(event=event, actor=request.user, **form.cleaned_data)
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
        else:
            messages.success(
                request,
                _("Dopisano zdarzenie korygujące; historia pozostała bez zmian."),
            )
    target = event.print_request_id
    if target:
        return redirect("printing:platform_detail", request_id=target)
    return redirect("printing:platform_queue")


@superuser_required
@require_GET
def run_status(request, request_id):
    print_request = get_object_or_404(PrintRequest, pk=request_id)
    run = PrintRun.objects.filter(print_request=print_request).prefetch_related("jobs").first()
    return render(
        request,
        "printing/partials/run_status.html",
        {"print_request": print_request, "run": run},
    )


@superuser_required
@require_GET
def package_download(request, package_id):
    package = get_object_or_404(
        PrintPackage.objects.select_related("print_run__print_request", "print_run__tenant"),
        pk=package_id,
    )
    path = resolve_package_path(package)
    if not path.is_file():
        raise Http404(_("Pakiet produkcyjny nie istnieje."))
    content = path.read_bytes()
    if len(content) != package.size_bytes:
        raise Http404(_("Pakiet produkcyjny nie przeszedł kontroli rozmiaru."))
    from card_artwork.services import bytes_sha256

    if bytes_sha256(content) != package.sha256:
        raise Http404(_("Pakiet produkcyjny nie przeszedł kontroli sumy."))
    AuditEvent.objects.create(
        tenant=package.print_run.tenant,
        actor=request.user,
        action="printing.package_downloaded",
        object_type="PrintPackage",
        object_id=str(package.pk),
        metadata={
            "run_id": package.print_run_id,
            "request_id": package.print_run.print_request_id,
            "sha256": package.sha256,
        },
    )
    return FileResponse(
        path.open("rb"),
        as_attachment=True,
        filename=f"production-run-{package.print_run_id}.zip",
        content_type="application/zip",
    )


@superuser_required
@require_POST
def legacy_preview(request):
    form = LegacyPreviewForm(request.POST)
    preview = None
    confirm_form = None
    if form.is_valid():
        try:
            preview = legacy_reconciliation_preview(**form.cleaned_data)
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            confirm_form = LegacyConfirmForm(
                initial={
                    "tenant_id": preview["tenant"].pk,
                    "batch_id": preview["batch"].pk,
                    "start_number": preview["start_number"],
                    "end_number": preview["end_number"],
                    "expected_count": preview["count"],
                }
            )
    if request.headers.get("HX-Request") == "true":
        return render(
            request,
            "printing/partials/legacy_preview.html",
            {"form": form, "legacy_preview": preview, "legacy_confirm_form": confirm_form},
            status=200 if preview else 400,
        )
    context = _platform_context(
        legacy_preview=preview,
        legacy_confirm_form=confirm_form,
    )
    context["legacy_preview_form"] = form
    return render(request, "printing/platform_print_center.html", context, status=200 if preview else 400)


@superuser_required
@require_POST
def legacy_confirm(request):
    form = LegacyConfirmForm(request.POST)
    if form.is_valid():
        tenant = get_object_or_404(Tenant, pk=form.cleaned_data["tenant_id"])
        from cards.models import CardBatch

        batch = get_object_or_404(
            CardBatch,
            pk=form.cleaned_data["batch_id"],
            tenant=tenant,
        )
        values = form.cleaned_data
        try:
            events = confirm_legacy_reconciliation(
                tenant=tenant,
                batch=batch,
                start_number=values["start_number"],
                end_number=values["end_number"],
                expected_count=values["expected_count"],
                event_types=values["event_types"],
                actor=request.user,
                occurred_at=values["occurred_at"],
                reference=values["reference"],
                notes=values["notes"],
            )
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
        else:
            messages.success(
                request,
                _("Dopisano %(count)s zdarzeń historycznych.")
                % {"count": len(events)},
            )
            return redirect("printing:platform_queue")
    else:
        messages.error(request, _("Potwierdzenie nie odpowiada podglądowi."))
    return redirect("printing:platform_queue")


__all__ = [
    "allocate_request",
    "approve_request",
    "cancel_request",
    "correct_event",
    "fulfill_request",
    "legacy_confirm",
    "legacy_preview",
    "package_download",
    "platform_print_center",
    "platform_request_detail",
    "reject_request",
    "run_status",
    "submit_request",
    "tenant_printing",
]
