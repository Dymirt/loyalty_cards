"""Tenant-owner and platform-operator billing HTTP adapters."""

from uuid import uuid4

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from tenants.authorization import can_manage_billing, superuser_required
from tenants.models import Tenant

from .forms import (
    CardPackForm,
    PlanForm,
    PlanVersionPublishForm,
    PriceBookForm,
    PriceBookVersionPublishForm,
    PrintQuoteForm,
    TenantSubscriptionForm,
)
from .models import CardPack, PlanVersion, PriceBookVersion, Quote, TenantSubscription
from .services import accept_quote, create_print_quote, tenant_billing_summary


def _tenant_or_forbidden(request, tenant_slug):
    tenant = get_object_or_404(Tenant, slug=tenant_slug, is_active=True)
    if not can_manage_billing(request.user, tenant):
        return tenant, HttpResponseForbidden(
            "Nie masz uprawnień do rozliczeń tej firmy."
        )
    return tenant, None


def _quote_form(*, subscription, data=None):
    currency = subscription.plan_version.currency if subscription else None
    initial = {"idempotency_key": f"print-quote:{uuid4()}"}
    return PrintQuoteForm(data, currency=currency, initial=initial)


@login_required
@require_GET
def tenant_billing(request, tenant_slug):
    tenant, forbidden = _tenant_or_forbidden(request, tenant_slug)
    if forbidden:
        return forbidden
    summary = tenant_billing_summary(tenant=tenant)
    return render(
        request,
        "billing/tenant_billing.html",
        {
            "tenant": tenant,
            "active_nav": "billing",
            "can_manage_billing": True,
            "can_manage_integrations": True,
            "can_manage_card_designs": True,
            "can_manage_printing": True,
            "quote_form": _quote_form(subscription=summary["subscription"]),
            "quotes": Quote.objects.filter(tenant=tenant)
            .select_related("price_book_version", "price_book_version__price_book")
            .prefetch_related("lines")[:20],
            **summary,
        },
    )


@login_required
@require_POST
def create_quote(request, tenant_slug):
    tenant, forbidden = _tenant_or_forbidden(request, tenant_slug)
    if forbidden:
        return forbidden
    summary = tenant_billing_summary(tenant=tenant)
    form = _quote_form(subscription=summary["subscription"], data=request.POST)
    quote = None
    if form.is_valid():
        try:
            quote, created = create_print_quote(
                tenant=tenant,
                quantity=form.cleaned_data["quantity"],
                price_book_version=form.cleaned_data["price_book_version"],
                idempotency_key=form.cleaned_data["idempotency_key"],
                actor=request.user,
            )
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            if request.headers.get("HX-Request") != "true":
                messages.success(
                    request,
                    "Utworzono kalkulację." if created else "Ta kalkulacja już istnieje.",
                )
                return redirect("billing:tenant", tenant_slug=tenant.slug)
    if request.headers.get("HX-Request") == "true":
        return render(
            request,
            "billing/partials/quote_result.html",
            {"tenant": tenant, "form": form, "quote": quote},
            status=200 if quote else 400,
        )
    messages.error(request, "Nie udało się utworzyć kalkulacji.")
    return render(
        request,
        "billing/tenant_billing.html",
        {
            "tenant": tenant,
            "active_nav": "billing",
            "can_manage_billing": True,
            "can_manage_integrations": True,
            "can_manage_card_designs": True,
            "can_manage_printing": True,
            "quote_form": form,
            "quotes": Quote.objects.filter(tenant=tenant).prefetch_related("lines")[:20],
            **summary,
        },
        status=400,
    )


@login_required
@require_POST
def accept_tenant_quote(request, tenant_slug, quote_id):
    tenant, forbidden = _tenant_or_forbidden(request, tenant_slug)
    if forbidden:
        return forbidden
    quote = get_object_or_404(Quote, pk=quote_id, tenant=tenant)
    try:
        quote, created = accept_quote(quote=quote)
    except ValidationError as exc:
        messages.error(request, "; ".join(exc.messages))
    else:
        messages.success(
            request,
            "Zaakceptowano kalkulację." if created else "Kalkulacja była już zaakceptowana.",
        )
    return redirect("billing:tenant", tenant_slug=tenant.slug)


def _platform_forms(bound_action=None, post_data=None):
    def data_for(action):
        return post_data if bound_action == action else None

    return {
        "plan_form": PlanForm(data_for("create_plan"), prefix="plan"),
        "plan_version_form": PlanVersionPublishForm(
            data_for("publish_plan_version"), prefix="plan_version"
        ),
        "price_book_form": PriceBookForm(
            data_for("create_price_book"), prefix="price_book"
        ),
        "price_book_version_form": PriceBookVersionPublishForm(
            data_for("publish_price_book_version"), prefix="price_book_version"
        ),
        "subscription_form": TenantSubscriptionForm(
            data_for("create_subscription"), prefix="subscription"
        ),
        "card_pack_form": CardPackForm(data_for("create_card_pack"), prefix="card_pack"),
    }


@superuser_required
@require_http_methods(["GET", "POST"])
def platform_billing(request):
    action = request.POST.get("action") if request.method == "POST" else None
    forms = _platform_forms(action, request.POST if request.method == "POST" else None)
    if request.method == "POST":
        form_by_action = {
            "create_plan": forms["plan_form"],
            "publish_plan_version": forms["plan_version_form"],
            "create_price_book": forms["price_book_form"],
            "publish_price_book_version": forms["price_book_version_form"],
            "create_subscription": forms["subscription_form"],
            "create_card_pack": forms["card_pack_form"],
        }
        form = form_by_action.get(action)
        if form is None:
            return HttpResponseForbidden("Nieprawidłowa operacja rozliczeniowa.")
        if form.is_valid():
            try:
                if action in {"publish_plan_version", "publish_price_book_version"}:
                    form.save(actor=request.user)
                else:
                    instance = form.save(commit=False)
                    instance.full_clean()
                    instance.save()
            except ValidationError as exc:
                form.add_error(None, exc)
            else:
                messages.success(request, "Zapisano konfigurację rozliczeniową.")
                return redirect("billing:platform")
    return render(
        request,
        "billing/platform_billing.html",
        {
            **forms,
            "plan_versions": PlanVersion.objects.select_related("plan").all()[:30],
            "price_book_versions": PriceBookVersion.objects.select_related(
                "price_book"
            ).all()[:30],
            "subscriptions": TenantSubscription.objects.select_related(
                "tenant", "plan_version", "plan_version__plan"
            ).all()[:30],
            "card_packs": CardPack.objects.select_related("tenant").all()[:30],
        },
    )


__all__ = [
    "accept_tenant_quote",
    "create_quote",
    "platform_billing",
    "tenant_billing",
]
