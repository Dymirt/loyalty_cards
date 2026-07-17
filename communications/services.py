"""Tenant-branded email delivery consuming already-issued Wallet artifacts."""

from html import escape
from pathlib import Path

from django.conf import settings
from django.core.mail import EmailMultiAlternatives, get_connection

from integrations.contracts import SystemCheckResult

from cards.codes import card_number, normalize_card_code
from wallets.services import apple_pass_path, wallet_identity


def _customer_apple_pass(customer):
    wallet = wallet_identity(customer)
    if wallet.apple_pass_path:
        stored = Path(settings.MEDIA_ROOT) / wallet.apple_pass_path
        if stored.is_file():
            return stored
    return apple_pass_path(customer.klient_id)


def send_pass_email(customer) -> int:
    if not customer.email:
        raise ValueError("The customer does not have an email address.")
    barcode = normalize_card_code(customer.klient_id)
    number = card_number(barcode)
    pass_path = _customer_apple_pass(customer)
    if not pass_path.is_file():
        raise FileNotFoundError(
            f"Apple Wallet pass is not available for customer {customer.pk}."
        )
    customer_name = " ".join(
        part for part in (customer.first_name, customer.last_name) if part
    )
    brand = customer.tenant.brand
    public_name = brand.public_name or customer.tenant.name
    signature = brand.email_signature or public_name
    logo_path = brand.logo_path or "logo_atelier_cafe.png"
    safe_name = escape(customer_name)
    safe_public_name = escape(public_name)
    safe_signature = escape(signature)
    safe_google_url = escape(customer.google_jwt_url or "", quote=True)
    subject = brand.email_subject or f"Twoja karta gościa {public_name}"
    text_content = f"""Dzień dobry {customer_name},

Twoja karta lojalnościowa {public_name} jest gotowa.
Google Wallet: {customer.google_jwt_url or ''}
Apple Wallet: karta w załączniku (.pkpass)

Pozdrawiamy,
{signature}
"""
    html_content = f"""<!doctype html>
<html lang="pl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"></head>
<body style="margin:0;padding:0;background:#f5f5f7">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr><td align="center" style="padding:24px 12px">
    <table role="presentation" width="600" cellpadding="0" cellspacing="0" style="max-width:600px;background:#fff;border-radius:12px;overflow:hidden">
      <tr><td align="center" style="padding:24px 24px 8px"><img src="{settings.APP_BASE_URL}/media/{escape(logo_path, quote=True)}" width="120" alt="{safe_public_name}" style="display:block;height:auto"></td></tr>
      <tr><td style="padding:8px 24px;font-family:Arial,sans-serif;color:#111;font-size:18px"><p>Dzień dobry {safe_name},</p><p>Twoja karta lojalnościowa {safe_public_name} jest gotowa.</p></td></tr>
      <tr><td align="center" style="padding:0 24px 8px"><img src="{settings.APP_BASE_URL}/media/cards/card-{number}/{barcode}_front.jpg" width="552" alt="Karta lojalnościowa" style="display:block;width:100%;max-width:552px;height:auto;border-radius:10px"></td></tr>
      <tr><td align="center" style="padding:8px 24px 24px"><a href="{safe_google_url}">Dodaj do Google Wallet</a></td></tr>
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
    message.attach(
        filename="atelier_card.pkpass",
        content=pass_path.read_bytes(),
        mimetype="application/vnd.apple.pkpass",
    )
    return message.send()


def smtp_system_check():
    if settings.EMAIL_BACKEND != "django.core.mail.backends.smtp.EmailBackend":
        return SystemCheckResult(
            ok=False,
            summary="Backend SMTP nie jest aktywny.",
            details=("Skonfiguruj EMAIL_BACKEND dla SMTP.",),
        )
    if not settings.EMAIL_HOST:
        return SystemCheckResult(
            ok=False,
            summary="Serwer SMTP nie jest skonfigurowany.",
        )
    connection = get_connection(fail_silently=False)
    try:
        opened = connection.open()
        if opened is False:
            return SystemCheckResult(
                ok=False,
                summary="Nie udało się otworzyć połączenia SMTP.",
            )
    finally:
        connection.close()
    return SystemCheckResult(
        ok=True,
        summary="Logowanie do serwera SMTP działa.",
        details=("Nie wysłano wiadomości testowej.",),
    )


__all__ = ["send_pass_email", "smtp_system_check"]
