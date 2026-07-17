"""Public enrollment HTTP adapter."""

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from cards.models import PhysicalCard
from enrollment.jobs import enqueue_registration_followups as start_registration_followups
from tenants.authorization import get_public_tenant

from .forms import LoyaltyCustomerRegistrationForm, registration_form_data
from .services import register_customer_with_card


def _render_registration(request, form, tenant, *, tenant_slug=None, status=200):
    form_action = (
        reverse("dotykacka:tenant_register", args=[tenant.slug])
        if tenant_slug
        else reverse("dotykacka:register")
    )
    return render(
        request,
        "customers/register.html",
        {"form": form, "form_action": form_action, "tenant": tenant},
        status=status,
    )


@require_http_methods(["GET", "POST"])
def register_customer_form(request, tenant_slug=None):
    tenant = get_public_tenant(tenant_slug)
    if request.method == "GET":
        return _render_registration(
            request,
            LoyaltyCustomerRegistrationForm(tenant=tenant),
            tenant,
            tenant_slug=tenant_slug,
        )
    form = LoyaltyCustomerRegistrationForm(
        registration_form_data(request.POST),
        tenant=tenant,
    )
    if not form.is_valid():
        return _render_registration(
            request,
            form,
            tenant,
            tenant_slug=tenant_slug,
            status=400,
        )
    try:
        customer = register_customer_with_card(tenant=tenant, cleaned_data=form.cleaned_data)
    except (IntegrityError, PhysicalCard.DoesNotExist, ValidationError) as exc:
        if isinstance(exc, ValidationError) and not isinstance(exc, IntegrityError):
            form.add_error(None, "; ".join(exc.messages))
        else:
            form.add_error("barcode", "Ta karta już istnieje w bazie danych.")
        return _render_registration(
            request,
            form,
            tenant,
            tenant_slug=tenant_slug,
            status=409,
        )
    # The local customer/card/consent transaction has committed; follow-ups
    # are persistent database jobs, never web-process threads.
    start_registration_followups(customer.pk)
    messages.success(request, "Zarejestrowano kartę klienta.")
    return redirect("index")
