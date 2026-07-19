"""Deployment checks for public legal/contact configuration."""

from django.conf import settings
from django.core.checks import Error, Tags, register
from django.core.exceptions import ValidationError
from django.core.validators import validate_email


@register(Tags.security)
def marketing_legal_configuration(app_configs, **kwargs):
    errors = []
    if not settings.MARKETING_LEGAL_NAME.strip():
        errors.append(
            Error(
                "MARKETING_LEGAL_NAME must identify the public site operator.",
                id="marketing.E001",
            )
        )
    try:
        validate_email(settings.MARKETING_CONTACT_EMAIL)
    except ValidationError:
        errors.append(
            Error(
                "MARKETING_CONTACT_EMAIL must be a valid public contact address.",
                id="marketing.E002",
            )
        )
    if not settings.MARKETING_PRIVACY_VERSION.strip():
        errors.append(
            Error(
                "MARKETING_PRIVACY_VERSION must identify the consent policy.",
                id="marketing.E003",
            )
        )
    if not settings.MARKETING_TERMS_VERSION.strip():
        errors.append(
            Error(
                "MARKETING_TERMS_VERSION must identify the public terms.",
                id="marketing.E004",
            )
        )
    return errors
