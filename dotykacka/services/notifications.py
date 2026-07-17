"""Customer notifications that consume already-generated Wallet artifacts."""

from html import escape

from django.conf import settings
from django.core.mail import EmailMultiAlternatives

from dotykacka.card_codes import card_number, normalize_card_code
from dotykacka.models import Klient

from .wallets import apple_pass_path


def send_pass_email(klient: Klient) -> int:
    """Send one branded email; this function never generates or mutates a pass."""

    if not klient.email:
        raise ValueError("The customer does not have an email address.")

    barcode = normalize_card_code(klient.klient_id)
    number = card_number(barcode)
    pass_path = apple_pass_path(barcode)
    if not pass_path.is_file():
        raise FileNotFoundError(f"Apple Wallet pass is not available for customer {klient.pk}.")

    customer_name = " ".join(
        part for part in (klient.first_name, klient.last_name) if part
    )
    brand = klient.tenant.brand
    public_name = brand.public_name or klient.tenant.name
    signature = brand.email_signature or public_name
    logo_path = brand.logo_path or "logo_atelier_cafe.png"
    safe_name = escape(customer_name)
    safe_public_name = escape(public_name)
    safe_signature = escape(signature)
    safe_google_url = escape(klient.google_jwt_url or "", quote=True)
    pass_file_name = pass_path.name

    subject = brand.email_subject or f"Twoja karta gościa {public_name}"
    text_content = f"""Dzień dobry {customer_name},

Twoja karta lojalnościowa Atelier Café jest gotowa.
Google Wallet: {klient.google_jwt_url or ''}
Apple Wallet: karta w załączniku (.pkpass)

Pozdrawiamy,
{signature}
"""
    html_content = f"""<!doctype html>
<html lang="pl">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width"></head>
<body style="margin:0;padding:0;background:#f5f5f7">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
    <tr><td align="center" style="padding:24px 12px">
      <table role="presentation" width="600" cellpadding="0" cellspacing="0"
             style="max-width:600px;background:#fff;border-radius:12px;overflow:hidden">
        <tr><td align="center" style="padding:24px 24px 8px">
          <img src="{settings.APP_BASE_URL}/media/{escape(logo_path, quote=True)}"
               width="120" alt="{safe_public_name}" style="display:block;height:auto">
        </td></tr>
        <tr><td style="padding:8px 24px;font-family:Arial,sans-serif;color:#111;font-size:18px">
          <p>Dzień dobry {safe_name},</p>
          <p>Twoja karta lojalnościowa Atelier Café jest gotowa.</p>
        </td></tr>
        <tr><td align="center" style="padding:0 24px 8px">
          <img src="{settings.APP_BASE_URL}/media/cards/card-{number}/{barcode}_front.jpg"
               width="552" alt="Karta lojalnościowa"
               style="display:block;width:100%;max-width:552px;height:auto;border-radius:10px">
        </td></tr>
        <tr><td align="center" style="padding:8px 24px 24px">
          <a href="{safe_google_url}">Dodaj do Google Wallet</a>
          &nbsp;|&nbsp;
          <a href="{settings.APP_BASE_URL}/media/output_passes/{pass_file_name}">Dodaj do Apple Wallet</a>
        </td></tr>
        <tr><td style="padding:0 24px 24px;font-family:Arial,sans-serif;color:#444;font-size:14px">
          Pozdrawiamy,<br>{safe_signature}
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""

    message = EmailMultiAlternatives(
        subject,
        text_content,
        settings.DEFAULT_FROM_EMAIL,
        [klient.email],
    )
    message.attach_alternative(html_content, "text/html")
    message.attach(
        filename="atelier_card.pkpass",
        content=pass_path.read_bytes(),
        mimetype="application/vnd.apple.pkpass",
    )
    return message.send()
