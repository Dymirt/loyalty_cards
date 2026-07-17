"""Legacy provider views and compatibility imports for extracted domains."""

import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_POST

import dotykacka.api_utils as dotykacka_api
from card_artwork.views import card_artifact_download, card_design_settings
from cards.codes import CardCodeError, parse_card_code
from cards.views import platform_print_center
from customers.models import Customer
from customers.views import get_all_customers as get_all_costumers
from enrollment.views import register_customer_form
from integrations.services import enqueue_job
from integrations.views import integration_settings
from tenants.authorization import (
    can_manage_integrations,
    get_default_tenant,
    superuser_required,
)
from tenants.models import Tenant
from tenants.views import tenant_portal

from .brevo import send_contact_to_brevo
from .forms import (
    BrevoIntegrationForm,
    DotykackaIntegrationForm,
    GoogleWalletIntegrationForm,
)
from .models import AuditEvent, IntegrationConnection
from .services.notifications import send_pass_email
from .services.wallets import generate_google_wallet_for_klient


logger = logging.getLogger(__name__)


@superuser_required
def get_acces_token(request):
    tenant = get_default_tenant()
    try:
        connection = dotykacka_api.get_dotykacka_connection(tenant)
        access_token = dotykacka_api.get_valid_access_token(connection)
    except Exception as exc:
        logger.warning(
            "dotykacka_access_token_unavailable",
            extra={"error_type": type(exc).__name__},
        )
        access_token = None
    return render(
        request,
        "dotykacka/access_token.html",
        {
            "access_token_available": bool(access_token),
            "tenant": tenant,
            "active_nav": "access_token",
        },
    )


def call_register_dotykacka_customer_async(customer: Customer):
    """Deprecated name; creates a durable POS job instead of a thread."""

    connection = IntegrationConnection.objects.filter(
        tenant=customer.tenant,
        provider=IntegrationConnection.Provider.DOTYKACKA,
        enabled=True,
    ).first()
    return enqueue_job(
        tenant=customer.tenant,
        connection=connection,
        kind="pos.dotykacka.customer_upsert",
        idempotency_key=f"legacy:{customer.pk}:pos.dotykacka.customer_upsert:v1",
        payload={"customer_id": customer.pk},
    )


def update_klient_google_jwt_url(klient_id: int):
    try:
        customer = Customer.objects.get(pk=klient_id)
    except Customer.DoesNotExist:
        return None
    return generate_google_wallet_for_klient(customer)


def update_klient_google_jwt_url_async(klient_id: int):
    """Deprecated name; creates a restart-safe Wallet job."""

    customer = Customer.objects.get(pk=klient_id)
    connection = IntegrationConnection.objects.filter(
        tenant=customer.tenant,
        provider=IntegrationConnection.Provider.GOOGLE_WALLET,
        enabled=True,
    ).first()
    return enqueue_job(
        tenant=customer.tenant,
        connection=connection,
        kind="wallet.google.issue",
        idempotency_key=f"legacy:{customer.pk}:wallet.google.issue:v1",
        payload={"customer_id": customer.pk},
    )


@superuser_required
@require_POST
def send_pass(request, barcode):
    tenant = get_default_tenant()
    try:
        normalized_barcode = parse_card_code(
            barcode,
            expected_prefix=tenant.card_prefix,
        ).value
        customer = Customer.objects.get(tenant=tenant, klient_id=normalized_barcode)
        send_pass_email(customer)
    except CardCodeError:
        messages.error(request, "Nieprawidłowy numer karty.")
    except Customer.DoesNotExist:
        messages.error(request, "Nie znaleziono klienta.")
    except FileNotFoundError:
        messages.error(request, "Nie znaleziono pliku karty.")
    except Exception as exc:
        logger.error("single_pass_email_failed", extra={"error_type": type(exc).__name__})
        messages.error(request, "Nie udało się wysłać karty.")
    else:
        messages.success(request, "Karta została wysłana.")
    return redirect("dotykacka:customers")


@superuser_required
@require_POST
def add_all_to_brevo(request):
    tenant = get_default_tenant()
    success_count = 0
    fail_count = 0
    for customer in Customer.objects.filter(tenant=tenant).iterator(chunk_size=200):
        try:
            if send_contact_to_brevo(customer):
                success_count += 1
        except Exception as exc:
            fail_count += 1
            logger.warning(
                "brevo_contact_sync_failed",
                extra={"klient_pk": customer.pk, "error_type": type(exc).__name__},
            )
    messages.success(request, f"Zsynchronizowano {success_count} kontaktów (nieudane: {fail_count}).")
    return redirect("dotykacka:customers")


@superuser_required
@require_POST
def generate_jwt_passes(request):
    tenant = get_default_tenant()
    success_count = 0
    fail_count = 0
    for customer in Customer.objects.filter(tenant=tenant).iterator(chunk_size=200):
        if not customer.klient_id:
            continue
        try:
            generate_google_wallet_for_klient(customer)
            success_count += 1
        except Exception as exc:
            fail_count += 1
            logger.warning(
                "google_wallet_generation_failed",
                extra={"klient_pk": customer.pk, "error_type": type(exc).__name__},
            )
    messages.success(request, f"Wygenerowano {success_count} kart Google Wallet (nieudane: {fail_count}).")
    return redirect("dotykacka:customers")


@superuser_required
@require_POST
def send_all_passes(request):
    tenant = get_default_tenant()
    success_count = 0
    fail_count = 0
    for customer in Customer.objects.filter(tenant=tenant).iterator(chunk_size=200):
        if not customer.email or not customer.klient_id:
            continue
        try:
            send_pass_email(customer)
            success_count += 1
        except Exception as exc:
            fail_count += 1
            logger.warning(
                "bulk_pass_email_failed",
                extra={"klient_pk": customer.pk, "error_type": type(exc).__name__},
            )
    logger.info(
        "bulk_pass_email_completed",
        extra={"success_count": success_count, "fail_count": fail_count},
    )
    messages.success(request, f"Wysłano {success_count} kart (nieudane: {fail_count}).")
    return redirect("dotykacka:customers")


__all__ = [
    "add_all_to_brevo",
    "call_register_dotykacka_customer_async",
    "card_artifact_download",
    "card_design_settings",
    "generate_jwt_passes",
    "get_acces_token",
    "get_all_costumers",
    "integration_settings",
    "platform_print_center",
    "register_customer_form",
    "send_all_passes",
    "send_pass",
    "tenant_portal",
    "update_klient_google_jwt_url",
    "update_klient_google_jwt_url_async",
]
