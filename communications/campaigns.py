"""Campaign composition, audience snapshots, scheduling, and delivery."""

import re
from email.mime.image import MIMEImage
from html import escape

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.db.models import OuterRef, Subquery
from django.utils import timezone
from django.utils.translation import gettext as _

from cards.models import PhysicalCard
from customers.models import ConsentRecord, Customer
from integrations.contracts import IntegrationError
from integrations.services import enqueue_job

from .ai import generate_campaign_copy
from .models import CampaignAsset, CampaignRecipient, EmailCampaign


CAMPAIGN_EMAIL_JOB = "communications.email.campaign"
DEFAULT_ACCENT = "#9A3C1F"
DEFAULT_BACKGROUND = "#F5F2EB"


def eligible_campaign_customers(tenant):
    latest_consent = ConsentRecord.objects.filter(
        tenant=tenant,
        customer_id=OuterRef("pk"),
        purpose="marketing",
    ).order_by("-recorded_at", "-pk")
    return (
        Customer.objects.filter(
            tenant=tenant,
            physical_card__status=PhysicalCard.Status.ASSIGNED,
            email__isnull=False,
        )
        .exclude(email="")
        .annotate(
            latest_consent_granted=Subquery(latest_consent.values("granted")[:1]),
            latest_consent_revoked_at=Subquery(latest_consent.values("revoked_at")[:1]),
        )
        .filter(latest_consent_granted=True, latest_consent_revoked_at=None)
        .order_by("pk")
    )


def eligible_recipient_count(tenant):
    return eligible_campaign_customers(tenant).count()


def add_campaign_assets(*, campaign, uploads, actor):
    assets = []
    for upload in uploads:
        asset = CampaignAsset(
            tenant=campaign.tenant,
            campaign=campaign,
            image=upload,
            original_name=(upload.name or "material")[:240],
            content_type=(getattr(upload, "content_type", "") or "")[:80],
            created_by=actor,
        )
        asset.full_clean(exclude=("image",))
        asset.save()
        assets.append(asset)
    return assets


def local_campaign_copy(campaign):
    brand_name = campaign.tenant.brand.public_name or campaign.tenant.name
    goal = " ".join(campaign.goal.split())
    short_goal = re.split(r"(?<=[.!?])\s+", goal, maxsplit=1)[0][:120]
    subject = short_goal or _("Wiadomość od %(brand)s") % {"brand": brand_name}
    headline = (_("Nowość w %(brand)s") % {"brand": brand_name})[:100]
    links = campaign.reference_links
    return {
        "subject": subject[:160],
        "preheader": goal[:180],
        "headline": headline,
        "body_paragraphs": [
            goal[:500],
            (_("Dziękujemy, że jesteś częścią społeczności %(brand)s.") % {"brand": brand_name})[:500],
        ],
        "cta_label": _("Zobacz szczegóły") if links else "",
        "cta_url_index": 0 if links else -1,
        "accent_color": DEFAULT_ACCENT,
        "background_color": DEFAULT_BACKGROUND,
    }


def _safe_color(value, fallback):
    return value.upper() if re.fullmatch(r"#[0-9A-Fa-f]{6}", value or "") else fallback


def render_campaign_content(campaign, copy):
    brand = campaign.tenant.brand
    brand_name = brand.public_name or campaign.tenant.name
    signature = brand.email_signature or brand_name
    accent = _safe_color(copy.get("accent_color"), DEFAULT_ACCENT)
    background = _safe_color(copy.get("background_color"), DEFAULT_BACKGROUND)
    subject = str(copy.get("subject") or "")[:240]
    preheader = str(copy.get("preheader") or "")[:240]
    headline = str(copy.get("headline") or "")[:100]
    paragraphs = [str(value)[:500] for value in copy.get("body_paragraphs", [])[:4]]
    cta_index = copy.get("cta_url_index", -1)
    cta_url = ""
    if isinstance(cta_index, int) and 0 <= cta_index < len(campaign.reference_links):
        cta_url = campaign.reference_links[cta_index]
    cta_label = str(copy.get("cta_label") or "")[:48] if cta_url else ""
    paragraph_html = "".join(
        f'<p style="margin:0 0 18px;line-height:1.65">{escape(paragraph)}</p>'
        for paragraph in paragraphs
        if paragraph
    )
    image_rows = "".join(
        (
            '<tr><td style="padding:0 32px 16px">'
            f'<img src="cid:campaign-image-{index}" alt="" width="576" '
            'style="display:block;width:100%;height:auto;border-radius:14px">'
            "</td></tr>"
        )
        for index, _asset in enumerate(campaign.assets.all()[:3], start=1)
    )
    cta_html = ""
    if cta_url and cta_label:
        cta_html = (
            '<p style="margin:26px 0 6px">'
            f'<a href="{escape(cta_url, quote=True)}" '
            f'style="display:inline-block;background:{accent};color:#ffffff;text-decoration:none;'
            'font-weight:700;padding:13px 22px;border-radius:10px">'
            f"{escape(cta_label)}</a></p>"
        )
    safe_subject = escape(subject)
    safe_preheader = escape(preheader)
    safe_headline = escape(headline)
    safe_brand = escape(brand_name)
    safe_signature = escape(signature)
    html_content = f"""<!doctype html>
<html lang="pl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>{safe_subject}</title></head>
<body style="margin:0;padding:0;background:{background};color:#191713">
  <div style="display:none;max-height:0;overflow:hidden;opacity:0">{safe_preheader}</div>
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{background}"><tr><td align="center" style="padding:28px 12px">
    <table role="presentation" width="640" cellpadding="0" cellspacing="0" style="width:100%;max-width:640px;background:#fffdf8;border-radius:20px;overflow:hidden;border:1px solid #e7e5e4">
      <tr><td style="padding:28px 32px 22px;font-family:Arial,sans-serif;font-size:15px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:{accent}">{safe_brand}</td></tr>
      {image_rows}
      <tr><td style="padding:20px 32px 12px;font-family:Arial,sans-serif">
        <p style="margin:0 0 18px;font-size:16px;line-height:1.5">Dzień dobry {{{{ first_name }}}},</p>
        <h1 style="margin:0 0 20px;font-size:32px;line-height:1.15;color:#191713">{safe_headline}</h1>
        <div style="font-size:17px;line-height:1.65;color:#3f3b35">{paragraph_html}{cta_html}</div>
      </td></tr>
      <tr><td style="padding:24px 32px 30px;font-family:Arial,sans-serif;font-size:14px;line-height:1.6;color:#5f5a52;border-top:1px solid #e7e5e4">Pozdrawiamy,<br><strong>{safe_signature}</strong><br><span style="font-size:12px">Wiadomość wysłana do posiadacza karty lojalnościowej {safe_brand} na podstawie udzielonej zgody marketingowej.</span></td></tr>
    </table>
  </td></tr></table>
</body></html>"""
    text_paragraphs = "\n\n".join(paragraphs)
    cta_text = f"\n\n{cta_label}: {cta_url}" if cta_url and cta_label else ""
    text_content = (
        f"Dzień dobry {{{{ first_name }}}},\n\n{headline}\n\n{text_paragraphs}"
        f"{cta_text}\n\nPozdrawiamy,\n{signature}"
    )
    return subject, preheader, html_content, text_content


def generate_campaign_content(campaign):
    fallback_error = ""
    try:
        copy, model = generate_campaign_copy(campaign)
        source = EmailCampaign.GenerationSource.OPENAI
    except IntegrationError as exc:
        copy = local_campaign_copy(campaign)
        model = ""
        source = EmailCampaign.GenerationSource.LOCAL
        fallback_error = exc.error_code
    subject, preheader, html_content, text_content = render_campaign_content(campaign, copy)
    campaign.name = subject or campaign.goal[:160]
    campaign.subject = subject
    campaign.preheader = preheader
    campaign.html_content = html_content
    campaign.text_content = text_content
    campaign.content_snapshot = {**copy, "fallback_error": fallback_error}
    campaign.generation_source = source
    campaign.ai_model = model
    campaign.full_clean()
    campaign.save()
    return campaign, fallback_error


@transaction.atomic
def schedule_campaign(*, campaign, scheduled_for):
    campaign = EmailCampaign.objects.select_for_update().get(pk=campaign.pk)
    if campaign.status != EmailCampaign.Status.DRAFT:
        raise ValidationError(_("Tylko szkic można zaplanować."))
    if not campaign.html_content or not campaign.subject:
        raise ValidationError(_("Najpierw wygeneruj treść wiadomości."))
    customers = list(eligible_campaign_customers(campaign.tenant))
    if not customers:
        raise ValidationError(
            _("Brak odbiorców z przypisaną kartą, adresem e-mail i aktualną zgodą marketingową.")
        )
    campaign.status = EmailCampaign.Status.SCHEDULED
    campaign.scheduled_for = scheduled_for
    campaign.recipient_count = len(customers)
    campaign.sent_count = 0
    campaign.failed_count = 0
    campaign.full_clean()
    campaign.save()
    for customer in customers:
        recipient = CampaignRecipient(
            tenant=campaign.tenant,
            campaign=campaign,
            customer=customer,
            email_snapshot=customer.email,
        )
        recipient.full_clean()
        recipient.save()
        job = enqueue_job(
            tenant=campaign.tenant,
            kind=CAMPAIGN_EMAIL_JOB,
            idempotency_key=f"campaign:{campaign.pk}:recipient:{recipient.pk}:v1",
            payload={"campaign_recipient_id": recipient.pk},
            max_attempts=1,
        )
        job.available_at = scheduled_for
        job.save(update_fields=("available_at", "updated_at"))
        recipient.integration_job = job
        recipient.full_clean()
        recipient.save(update_fields=("integration_job", "updated_at"))
    return campaign


def personalized_campaign_content(recipient):
    first_name = escape((recipient.customer.first_name or "").strip() or _("Gościu"))
    return (
        recipient.campaign.html_content.replace("{{ first_name }}", first_name),
        recipient.campaign.text_content.replace("{{ first_name }}", first_name),
    )


def send_campaign_email(recipient):
    html_content, text_content = personalized_campaign_content(recipient)
    message = EmailMultiAlternatives(
        recipient.campaign.subject,
        text_content,
        settings.DEFAULT_FROM_EMAIL,
        [recipient.email_snapshot],
    )
    message.attach_alternative(html_content, "text/html")
    message.mixed_subtype = "related"
    for index, asset in enumerate(recipient.campaign.assets.all()[:3], start=1):
        asset.image.open("rb")
        try:
            subtype = (asset.content_type or "image/jpeg").partition("/")[2].lower()
            if subtype == "jpg":
                subtype = "jpeg"
            attachment = MIMEImage(asset.image.read(), _subtype=subtype)
        finally:
            asset.image.close()
        attachment.add_header("Content-ID", f"<campaign-image-{index}>")
        attachment.add_header(
            "Content-Disposition",
            "inline",
            filename=asset.original_name,
        )
        message.attach(attachment)
    return message.send()


@transaction.atomic
def refresh_campaign_delivery_status(campaign_id):
    campaign = EmailCampaign.objects.select_for_update().get(pk=campaign_id)
    sent = campaign.recipients.filter(status=CampaignRecipient.Status.SENT).count()
    failed = campaign.recipients.filter(status=CampaignRecipient.Status.FAILED).count()
    campaign.sent_count = sent
    campaign.failed_count = failed
    if sent + failed >= campaign.recipient_count:
        campaign.status = (
            EmailCampaign.Status.SENT if failed == 0 else EmailCampaign.Status.PARTIALLY_SENT
        )
        campaign.sent_at = timezone.now()
    elif sent or campaign.recipients.filter(status=CampaignRecipient.Status.SENDING).exists():
        campaign.status = EmailCampaign.Status.SENDING
    campaign.save(
        update_fields=(
            "sent_count",
            "failed_count",
            "status",
            "sent_at",
            "updated_at",
        )
    )
    return campaign


__all__ = [
    "CAMPAIGN_EMAIL_JOB",
    "add_campaign_assets",
    "eligible_campaign_customers",
    "eligible_recipient_count",
    "generate_campaign_content",
    "personalized_campaign_content",
    "refresh_campaign_delivery_status",
    "render_campaign_content",
    "schedule_campaign",
    "send_campaign_email",
]
