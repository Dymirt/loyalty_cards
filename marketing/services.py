"""Application services for public marketing leads."""

import hashlib
import json

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils.translation import gettext as _

from .models import MarketingLead


def _normalized_lead_content(cleaned_data):
    return {
        "full_name": cleaned_data["full_name"].strip(),
        "company_name": cleaned_data["company_name"].strip(),
        "email": cleaned_data["email"].strip().lower(),
        "phone": cleaned_data.get("phone", "").strip(),
        "message": cleaned_data["message"].strip(),
    }


@transaction.atomic
def record_marketing_lead(*, cleaned_data, source_path):
    content = _normalized_lead_content(cleaned_data)
    content_sha256 = hashlib.sha256(
        json.dumps(content, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    public_id = cleaned_data["submission_id"]
    existing = MarketingLead.objects.filter(public_id=public_id).first()
    if existing:
        if existing.content_sha256 != content_sha256:
            raise ValidationError(_("Identyfikator tego zgłoszenia kontaktowego został już użyty."))
        return existing, False
    consent_text = settings.MARKETING_PRIVACY_CONSENT_TEXT
    lead = MarketingLead(
        public_id=public_id,
        privacy_policy_version=settings.MARKETING_PRIVACY_VERSION,
        privacy_text_sha256=hashlib.sha256(consent_text.encode("utf-8")).hexdigest(),
        content_sha256=content_sha256,
        source_path=(source_path or "/kontakt/")[:300],
        **content,
    )
    lead.full_clean()
    try:
        with transaction.atomic():
            lead.save()
    except IntegrityError:
        existing = MarketingLead.objects.get(public_id=public_id)
        if existing.content_sha256 != content_sha256:
            raise ValidationError(
                _("Identyfikator tego zgłoszenia kontaktowego został już użyty.")
            )
        return existing, False
    return lead, True


__all__ = ["record_marketing_lead"]
