"""Tenant-branded email delivery consuming already-issued Wallet artifacts."""

import hashlib
from html import escape
from pathlib import Path

from django.conf import settings
from django.core.mail import EmailMultiAlternatives, get_connection
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from integrations.contracts import IntegrationError, SystemCheckResult

from cards.codes import CardCodeError
from wallets.services import apple_pass_path, wallet_identity

from .models import CommunicationDelivery


def customer_apple_pass(customer, *, create_identity=True):
    if create_identity:
        wallet = wallet_identity(customer)
    else:
        try:
            wallet = customer.wallet_pass
        except AttributeError:
            wallet = None
    if wallet and wallet.apple_pass_path:
        stored = Path(settings.MEDIA_ROOT) / wallet.apple_pass_path
        if stored.is_file():
            return stored
    try:
        return apple_pass_path(customer.klient_id)
    except CardCodeError:
        return (
            Path(settings.MEDIA_ROOT)
            / "output_passes"
            / "tenant-wallets"
            / f"{customer.tenant.slug}-{customer.klient_id}.pkpass"
        )


def email_subject_for(customer, brand_snapshot=None):
    brand_snapshot = brand_snapshot or {}
    public_name = (
        brand_snapshot.get("public_name")
        or customer.tenant.brand.public_name
        or customer.tenant.name
    )
    return (
        brand_snapshot.get("email_subject")
        or customer.tenant.brand.email_subject
        or f"Twoja karta gościa {public_name}"
    )


def send_pass_email(
    customer,
    *,
    brand_snapshot=None,
    application_link_url="",
    require_apple=True,
) -> int:
    if not customer.email:
        raise ValueError("The customer does not have an email address.")
    pass_path = customer_apple_pass(customer)
    if require_apple and not pass_path.is_file():
        raise FileNotFoundError(
            f"Apple Wallet pass is not available for customer {customer.pk}."
        )
    customer_name = " ".join(
        part for part in (customer.first_name, customer.last_name) if part
    )
    brand = customer.tenant.brand
    brand_snapshot = brand_snapshot or {}
    public_name = brand_snapshot.get("public_name") or brand.public_name or customer.tenant.name
    signature = brand_snapshot.get("email_signature") or brand.email_signature or public_name
    logo_path = brand_snapshot.get("logo_path") or brand.logo_path or "logo_atelier_cafe.png"
    safe_name = escape(customer_name)
    safe_public_name = escape(public_name)
    safe_signature = escape(signature)
    safe_google_url = escape(customer.google_jwt_url or "", quote=True)
    safe_application_url = escape(application_link_url or "", quote=True)
    subject = email_subject_for(customer, brand_snapshot)
    application_text = (
        f"Status i bezpieczne pobieranie: {application_link_url}\n"
        if application_link_url
        else ""
    )
    text_content = f"""Dzień dobry {customer_name},

Twoja karta lojalnościowa {public_name} jest gotowa.
Google Wallet: {customer.google_jwt_url or ''}
Apple Wallet: {'karta w załączniku (.pkpass)' if pass_path.is_file() else 'niedostępna'}
{application_text}

Pozdrawiamy,
{signature}
"""
    application_html = (
        f'<p><a href="{safe_application_url}">Sprawdź status i pobierz kartę</a></p>'
        if application_link_url
        else ""
    )
    google_html = (
        f'<a href="{safe_google_url}">Dodaj do Google Wallet</a>'
        if customer.google_jwt_url
        else "Google Wallet jest przygotowywany."
    )
    html_content = f"""<!doctype html>
<html lang="pl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"></head>
<body style="margin:0;padding:0;background:#f5f5f7">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr><td align="center" style="padding:24px 12px">
    <table role="presentation" width="600" cellpadding="0" cellspacing="0" style="max-width:600px;background:#fff;border-radius:12px;overflow:hidden">
      <tr><td align="center" style="padding:24px 24px 8px"><img src="{settings.APP_BASE_URL}/media/{escape(logo_path, quote=True)}" width="120" alt="{safe_public_name}" style="display:block;height:auto"></td></tr>
      <tr><td style="padding:8px 24px;font-family:Arial,sans-serif;color:#111;font-size:18px"><p>Dzień dobry {safe_name},</p><p>Twoja karta lojalnościowa {safe_public_name} jest gotowa.</p></td></tr>
      <tr><td align="center" style="padding:0 24px 8px;font-family:Arial,sans-serif;color:#444;font-size:14px">Podgląd i bezpieczne pobieranie karty są dostępne wyłącznie przez link statusu poniżej.</td></tr>
      <tr><td align="center" style="padding:8px 24px 24px">{google_html}{application_html}</td></tr>
      <tr><td style="padding:0 24px 24px;font-family:Arial,sans-serif;color:#444;font-size:14px">Pozdrawiamy,<br>{safe_signature}</td></tr>
    </table>
  </td></tr></table>
</body></html>"""
    message = EmailMultiAlternatives(
        subject,
        text_content,
        settings.DEFAULT_FROM_EMAIL,
        [customer.email],
    )
    message.attach_alternative(html_content, "text/html")
    if pass_path.is_file():
        message.attach(
            filename="loyalty-card.pkpass",
            content=pass_path.read_bytes(),
            mimetype="application/vnd.apple.pkpass",
        )
    return message.send()


@transaction.atomic
def begin_email_delivery(*, job, customer, subject, generation=1):
    existing = (
        CommunicationDelivery.objects.select_for_update()
        .filter(integration_job=job)
        .first()
    )
    if existing:
        if existing.status == CommunicationDelivery.Status.SENT:
            return existing, False
        if existing.status == CommunicationDelivery.Status.SENDING:
            existing.status = CommunicationDelivery.Status.OUTCOME_UNKNOWN
            existing.completed_at = timezone.now()
            existing.save(update_fields=("status", "completed_at"))
        raise IntegrationError(
            "A previous email attempt has an unknown outcome; use explicit resend.",
            error_code="email_delivery_outcome_unknown",
        )
    delivery = CommunicationDelivery(
        tenant=customer.tenant,
        customer=customer,
        integration_job=job,
        generation=generation,
        recipient_sha256=hashlib.sha256(
            customer.email.strip().lower().encode("utf-8")
        ).hexdigest(),
        subject_snapshot=subject,
        status=CommunicationDelivery.Status.SENDING,
        started_at=timezone.now(),
    )
    delivery.full_clean()
    delivery.save()
    return delivery, True


@transaction.atomic
def mark_email_delivery_sent(delivery):
    delivery = CommunicationDelivery.objects.select_for_update().get(pk=delivery.pk)
    if delivery.status == CommunicationDelivery.Status.SENT:
        return delivery
    if delivery.status != CommunicationDelivery.Status.SENDING:
        raise IntegrationError(error_code="email_delivery_outcome_unknown")
    delivery.status = CommunicationDelivery.Status.SENT
    delivery.completed_at = timezone.now()
    delivery.save(update_fields=("status", "completed_at"))
    return delivery


@transaction.atomic
def mark_email_delivery_unknown(delivery):
    delivery = CommunicationDelivery.objects.select_for_update().get(pk=delivery.pk)
    if delivery.status == CommunicationDelivery.Status.SENDING:
        delivery.status = CommunicationDelivery.Status.OUTCOME_UNKNOWN
        delivery.completed_at = timezone.now()
        delivery.save(update_fields=("status", "completed_at"))
    return delivery


def smtp_system_check():
    if settings.EMAIL_BACKEND != "django.core.mail.backends.smtp.EmailBackend":
        return SystemCheckResult(
            ok=False,
            summary=_("Backend SMTP nie jest aktywny."),
            details=(_("Skonfiguruj EMAIL_BACKEND dla SMTP."),),
        )
    if not settings.EMAIL_HOST:
        return SystemCheckResult(
            ok=False,
            summary=_("Serwer SMTP nie jest skonfigurowany."),
        )
    connection = get_connection(fail_silently=False)
    try:
        opened = connection.open()
        if opened is False:
            return SystemCheckResult(
                ok=False,
                summary=_("Nie udało się otworzyć połączenia SMTP."),
            )
    finally:
        connection.close()
    return SystemCheckResult(
        ok=True,
        summary=_("Logowanie do serwera SMTP działa."),
        details=(_("Nie wysłano wiadomości testowej."),),
    )


__all__ = [
    "begin_email_delivery",
    "customer_apple_pass",
    "email_subject_for",
    "mark_email_delivery_sent",
    "mark_email_delivery_unknown",
    "send_pass_email",
    "smtp_system_check",
]
