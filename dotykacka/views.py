"""HTTP views for the legacy single-tenant loyalty application."""

import logging
import mimetypes
from threading import Thread

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.http import FileResponse, Http404, HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods, require_POST

import dotykacka.api_utils as dotykacka_api
from dotykacka.brevo import send_contact_to_brevo

from .card_codes import CardCodeError, card_number, parse_card_code
from .forms import (
    BrevoIntegrationForm,
    CardDesignForm,
    DotykackaIntegrationForm,
    GoogleWalletIntegrationForm,
    LoyaltyCustomerRegistrationForm,
    TenantBrandForm,
    registration_form_data,
)
from .models import (
    AuditEvent,
    CardArtifact,
    CardDesign,
    IntegrationConnection,
    Klient,
    PhysicalCard,
    Tenant,
)
from .services.card_designs import (
    brand_snapshot_values,
    design_snapshot_values,
    generate_proof_artifacts,
    publish_card_design,
    render_card,
    resolve_artifact_path,
    spec_from_values,
)
from .services.notifications import send_pass_email
from .services.registration import start_registration_followups
from .services.wallets import generate_google_wallet_for_klient
from .tenancy import (
    can_access_tenant,
    can_manage_card_designs,
    can_manage_integrations,
    get_default_tenant,
    get_public_tenant,
)


logger = logging.getLogger(__name__)

superuser_required = user_passes_test(
    lambda user: user.is_active and user.is_superuser,
    login_url="/admin/login/",
)


def _render_registration(request, form, tenant, *, tenant_slug=None, status=200):
    form_action = (
        reverse("dotykacka:tenant_register", args=[tenant.slug])
        if tenant_slug
        else reverse("dotykacka:register")
    )
    return render(
        request,
        "dotykacka/register_customer_form.html",
        {
            "form": form,
            "form_action": form_action,
            "tenant": tenant,
        },
        status=status,
    )


@superuser_required
def get_acces_token(request):
    tenant = get_default_tenant()
    try:
        connection = dotykacka_api.get_dotykacka_connection(tenant)
        access_token = dotykacka_api.get_valid_access_token(connection)
    except Exception as exc:  # external configuration/API boundary
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


@superuser_required
def get_all_costumers(request):
    tenant = get_default_tenant()
    try:
        all_customers = dotykacka_api.get_all_customers(tenant)
        error = None
    except Exception as exc:  # external configuration/API boundary
        logger.warning(
            "dotykacka_customer_list_unavailable",
            extra={"error_type": type(exc).__name__},
        )
        all_customers = []
        error = "Nie udało się pobrać klientów z Dotykački."

    for customer in all_customers:
        try:
            customer["barcode_decode"] = str(card_number(customer.get("barcode")))
        except CardCodeError:
            customer["barcode_decode"] = ""

    return render(
        request,
        "dotykacka/customers.html",
        {
            "customers": all_customers,
            "error": error,
            "tenant": tenant,
            "active_nav": "customers",
        },
    )


@login_required
def tenant_portal(request, tenant_slug):
    tenant = get_object_or_404(
        Tenant.objects.select_related("brand"),
        slug=tenant_slug,
        is_active=True,
    )
    if not can_access_tenant(request.user, tenant):
        return HttpResponseForbidden("Nie masz dostępu do tej firmy.")

    integration_statuses = {
        connection.provider: connection.enabled
        for connection in IntegrationConnection.objects.filter(tenant=tenant)
    }
    return render(
        request,
        "dotykacka/tenant_portal.html",
        {
            "tenant": tenant,
            "active_nav": "overview",
            "can_manage_integrations": can_manage_integrations(request.user, tenant),
            "can_manage_card_designs": can_manage_card_designs(request.user, tenant),
            "customer_count": tenant.customers.count(),
            "available_card_count": tenant.physical_cards.filter(
                status=PhysicalCard.Status.AVAILABLE,
                customer__isnull=True,
            ).count(),
            "assigned_card_count": tenant.physical_cards.filter(
                status=PhysicalCard.Status.ASSIGNED,
                customer__isnull=False,
            ).count(),
            "integration_statuses": integration_statuses,
        },
    )


def _card_design_context(tenant, brand_form, design_form, proof=None):
    designs = CardDesign.objects.filter(tenant=tenant).select_related("brand_revision")
    current_design = designs.first()
    proof_artifacts = (
        CardArtifact.objects.filter(
            tenant=tenant,
            design=current_design,
            kind__in=(
                CardArtifact.Kind.PROOF_FRONT,
                CardArtifact.Kind.PROOF_BACK,
                CardArtifact.Kind.MANIFEST,
            ),
        )[:12]
        if current_design
        else []
    )
    return {
        "tenant": tenant,
        "brand_form": brand_form,
        "design_form": design_form,
        "designs": designs,
        "current_design": current_design,
        "proof": proof,
        "proof_artifacts": proof_artifacts,
        "active_nav": "card_design",
        "can_manage_integrations": True,
        "can_manage_card_designs": True,
    }


@login_required
@require_http_methods(["GET", "POST"])
def card_design_settings(request, tenant_slug):
    tenant = get_object_or_404(
        Tenant.objects.select_related("brand"),
        slug=tenant_slug,
        is_active=True,
    )
    if not can_manage_card_designs(request.user, tenant):
        return HttpResponseForbidden("Nie masz uprawnień do projektu kart tej firmy.")

    current_design = CardDesign.objects.filter(tenant=tenant).first()
    if request.method == "GET":
        brand_form = TenantBrandForm(instance=tenant.brand, prefix="brand")
        design_form = CardDesignForm(
            tenant=tenant,
            current_design=current_design,
            prefix="design",
        )
        return render(
            request,
            "dotykacka/card_design_settings.html",
            _card_design_context(tenant, brand_form, design_form),
        )

    brand_form = TenantBrandForm(
        request.POST,
        instance=tenant.brand,
        prefix="brand",
    )
    design_form = CardDesignForm(
        request.POST,
        request.FILES,
        tenant=tenant,
        current_design=current_design,
        prefix="design",
    )
    proof = None
    status = 400
    if brand_form.is_valid() and design_form.is_valid():
        design_values = design_snapshot_values(design_form.cleaned_data)
        try:
            spec = spec_from_values(
                tenant=tenant,
                values=design_values,
                background_upload=design_form.cleaned_data.get("background_image"),
                logo_upload=design_form.cleaned_data.get("logo_image"),
                fallback_design=current_design,
            )
            rendered = render_card(spec, f"{tenant.card_prefix}-1")
            proof = {
                **rendered.data_urls(),
                "checksum": spec.checksum,
                "crop_box": rendered.crop_box,
                "width_px": rendered.width_px,
                "height_px": rendered.height_px,
                "dpi": rendered.dpi,
            }
            status = 200
            if request.POST.get("action") == "publish":
                design = publish_card_design(
                    tenant=tenant,
                    actor=request.user,
                    brand_values=brand_snapshot_values(brand_form.cleaned_data),
                    design_values=design_values,
                    background_upload=design_form.cleaned_data.get("background_image"),
                    logo_upload=design_form.cleaned_data.get("logo_image"),
                )
                generate_proof_artifacts(design=design)
                AuditEvent.objects.create(
                    tenant=tenant,
                    actor=request.user,
                    action="card_design.published",
                    object_type="CardDesign",
                    object_id=str(design.pk),
                    metadata={
                        "version": design.version,
                        "checksum": design.design_checksum,
                    },
                )
                messages.success(request, f"Opublikowano projekt karty v{design.version}.")
                target = reverse(
                    "dotykacka:card_design_settings",
                    kwargs={"tenant_slug": tenant.slug},
                )
                if request.headers.get("HX-Request") == "true":
                    response = HttpResponse(status=204)
                    response["HX-Redirect"] = target
                    return response
                return redirect(target)
        except ValidationError as exc:
            design_form.add_error(None, exc)
            status = 400

    context = _card_design_context(tenant, brand_form, design_form, proof)
    if request.headers.get("HX-Request") == "true":
        return render(
            request,
            "dotykacka/partials/card_design_proof.html",
            context,
            status=status,
        )
    return render(request, "dotykacka/card_design_settings.html", context, status=status)


@login_required
def card_artifact_download(request, tenant_slug, artifact_id):
    tenant = get_object_or_404(Tenant, slug=tenant_slug, is_active=True)
    if not can_manage_card_designs(request.user, tenant):
        return HttpResponseForbidden("Nie masz dostępu do plików tej firmy.")
    artifact = get_object_or_404(CardArtifact, pk=artifact_id, tenant=tenant)
    path = resolve_artifact_path(artifact)
    if not path.is_file():
        raise Http404("Plik artefaktu nie istnieje.")
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return FileResponse(
        path.open("rb"),
        as_attachment=True,
        filename=path.name,
        content_type=content_type,
    )


@superuser_required
def platform_print_center(request):
    tenants = Tenant.objects.filter(is_active=True).annotate(
        customer_count=Count("customers", distinct=True),
        available_card_count=Count(
            "physical_cards",
            filter=Q(
                physical_cards__status=PhysicalCard.Status.AVAILABLE,
                physical_cards__customer__isnull=True,
            ),
            distinct=True,
        ),
        assigned_card_count=Count(
            "physical_cards",
            filter=Q(
                physical_cards__status=PhysicalCard.Status.ASSIGNED,
                physical_cards__customer__isnull=False,
            ),
            distinct=True,
        ),
    )
    return render(
        request,
        "dotykacka/platform_print_center.html",
        {"tenants": tenants, "platform_nav": "print_center"},
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
        with transaction.atomic():
            card = PhysicalCard.objects.select_for_update().get(
                tenant=tenant,
                code=form.cleaned_data["barcode"],
                status=PhysicalCard.Status.AVAILABLE,
                customer__isnull=True,
            )
            klient = Klient.objects.create(
                tenant=tenant,
                klient_id=form.cleaned_data["barcode"],
                email=form.cleaned_data["email"],
                phone=form.cleaned_data["phone"],
                first_name=form.cleaned_data["first_name"],
                last_name=form.cleaned_data["last_name"],
                google_jwt_url="",
            )
            card.customer = klient
            card.status = PhysicalCard.Status.ASSIGNED
            card.save(update_fields=["customer", "status"])
    except (IntegrityError, PhysicalCard.DoesNotExist):
        # The database uniqueness constraint closes the concurrent-registration race.
        form.add_error("barcode", "Ta karta już istnieje w bazie danych.")
        return _render_registration(
            request,
            form,
            tenant,
            tenant_slug=tenant_slug,
            status=409,
        )

    start_registration_followups(klient.pk)
    messages.success(request, "Zarejestrowano kartę klienta.")
    return redirect("index")


def call_register_dotykacka_customer_async(klient: Klient) -> Thread:
    """Compatibility wrapper for callers not yet moved to the shared workflow."""

    def worker():
        try:
            dotykacka_api.register_dotykacka_customer(
                klient.tenant,
                klient.klient_id,
                klient.first_name,
                klient.last_name,
                klient.email,
                klient.phone,
            )
        except Exception as exc:  # external API boundary
            logger.error(
                "dotykacka_customer_registration_failed",
                extra={
                    "klient_pk": klient.pk,
                    "error_type": type(exc).__name__,
                },
            )

    thread = Thread(target=worker, name=f"dotykacka-sync-{klient.pk}", daemon=True)
    thread.start()
    return thread


def update_klient_google_jwt_url(klient_id: int):
    """Compatibility wrapper around explicit Google Wallet generation."""

    try:
        klient = Klient.objects.get(pk=klient_id)
    except Klient.DoesNotExist:
        return None
    return generate_google_wallet_for_klient(klient)


def update_klient_google_jwt_url_async(klient_id: int) -> Thread:
    thread = Thread(
        target=update_klient_google_jwt_url,
        args=(klient_id,),
        name=f"google-wallet-{klient_id}",
        daemon=True,
    )
    thread.start()
    return thread


@superuser_required
@require_POST
def send_pass(request, barcode):
    tenant = get_default_tenant()
    try:
        normalized_barcode = parse_card_code(
            barcode,
            expected_prefix=tenant.card_prefix,
        ).value
        klient = Klient.objects.get(tenant=tenant, klient_id=normalized_barcode)
        send_pass_email(klient)
    except CardCodeError:
        messages.error(request, "Nieprawidłowy numer karty.")
    except Klient.DoesNotExist:
        messages.error(request, "Nie znaleziono klienta.")
    except FileNotFoundError:
        messages.error(request, "Nie znaleziono pliku karty.")
    except Exception as exc:  # email/filesystem boundary
        logger.error(
            "single_pass_email_failed",
            extra={"error_type": type(exc).__name__},
        )
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
    for klient in Klient.objects.filter(tenant=tenant).iterator(chunk_size=200):
        try:
            if send_contact_to_brevo(klient):
                success_count += 1
        except Exception as exc:  # external CRM boundary
            fail_count += 1
            logger.warning(
                "brevo_contact_sync_failed",
                extra={
                    "klient_pk": klient.pk,
                    "error_type": type(exc).__name__,
                },
            )

    messages.success(
        request,
        f"Zsynchronizowano {success_count} kontaktów (nieudane: {fail_count}).",
    )
    return redirect("dotykacka:customers")


@superuser_required
@require_POST
def generate_jwt_passes(request):
    tenant = get_default_tenant()
    success_count = 0
    fail_count = 0
    for klient in Klient.objects.filter(tenant=tenant).iterator(chunk_size=200):
        if not klient.klient_id:
            continue
        try:
            generate_google_wallet_for_klient(klient)
            success_count += 1
        except Exception as exc:  # signing/credential boundary
            fail_count += 1
            logger.warning(
                "google_wallet_generation_failed",
                extra={
                    "klient_pk": klient.pk,
                    "error_type": type(exc).__name__,
                },
            )

    messages.success(
        request,
        f"Wygenerowano {success_count} kart Google Wallet (nieudane: {fail_count}).",
    )
    return redirect("dotykacka:customers")


@superuser_required
@require_POST
def send_all_passes(request):
    tenant = get_default_tenant()
    success_count = 0
    fail_count = 0
    for klient in Klient.objects.filter(tenant=tenant).iterator(chunk_size=200):
        if not klient.email or not klient.klient_id:
            continue
        try:
            send_pass_email(klient)
            success_count += 1
        except Exception as exc:  # email/filesystem boundary
            fail_count += 1
            logger.warning(
                "bulk_pass_email_failed",
                extra={
                    "klient_pk": klient.pk,
                    "error_type": type(exc).__name__,
                },
            )

    logger.info(
        "bulk_pass_email_completed",
        extra={"success_count": success_count, "fail_count": fail_count},
    )
    messages.success(
        request,
        f"Wysłano {success_count} kart (nieudane: {fail_count}).",
    )
    return redirect("dotykacka:customers")


@login_required
@require_http_methods(["GET", "POST"])
def integration_settings(request, tenant_slug):
    tenant = get_object_or_404(Tenant, slug=tenant_slug, is_active=True)
    if not can_manage_integrations(request.user, tenant):
        return HttpResponseForbidden("Nie masz uprawnień do konfiguracji tej firmy.")

    connection_by_provider = {}
    for provider in IntegrationConnection.Provider.values:
        connection, _ = IntegrationConnection.objects.get_or_create(
            tenant=tenant,
            provider=provider,
        )
        connection_by_provider[provider] = connection

    form_classes = {
        IntegrationConnection.Provider.DOTYKACKA: DotykackaIntegrationForm,
        IntegrationConnection.Provider.BREVO: BrevoIntegrationForm,
        IntegrationConnection.Provider.GOOGLE_WALLET: GoogleWalletIntegrationForm,
    }
    forms = {
        provider: form_class(
            tenant=tenant,
            connection=connection_by_provider[provider],
            prefix=provider,
        )
        for provider, form_class in form_classes.items()
    }

    if request.method == "POST":
        provider = request.POST.get("provider")
        form_class = form_classes.get(provider)
        if form_class is None:
            return HttpResponseForbidden("Nieprawidłowy typ integracji.")
        form = form_class(
            request.POST,
            tenant=tenant,
            connection=connection_by_provider[provider],
            prefix=provider,
        )
        forms[provider] = form
        if form.is_valid():
            connection = form.save()
            AuditEvent.objects.create(
                tenant=tenant,
                actor=request.user,
                action="integration.updated",
                object_type="IntegrationConnection",
                object_id=str(connection.pk),
                metadata={
                    "provider": connection.provider,
                    "enabled": connection.enabled,
                },
            )
            messages.success(request, "Zapisano konfigurację integracji.")
            return redirect(
                "dotykacka:integration_settings",
                tenant_slug=tenant.slug,
            )

    return render(
        request,
        "dotykacka/integration_settings.html",
        {
            "tenant": tenant,
            "forms": forms,
            "connections": connection_by_provider,
            "active_nav": "integrations",
            "can_manage_integrations": True,
            "secret_status": {
                "dotykacka": connection_by_provider[
                    IntegrationConnection.Provider.DOTYKACKA
                ].has_secret("authorization_token"),
                "brevo": connection_by_provider[
                    IntegrationConnection.Provider.BREVO
                ].has_secret("api_key"),
            },
        },
    )
