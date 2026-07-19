"""Deployment checks for durable public enrollment links."""

from django.conf import settings
from django.core.checks import Error, Tags, register


@register(Tags.security)
def enrollment_link_ttl(app_configs, **kwargs):
    try:
        ttl_days = int(settings.ENROLLMENT_LINK_TTL_DAYS)
    except (TypeError, ValueError):
        ttl_days = 0
    if ttl_days <= 0:
        return [
            Error(
                "ENROLLMENT_LINK_TTL_DAYS must be a positive integer.",
                hint="Use a finite positive lifetime, for example 30 days.",
                id="enrollment.E001",
            )
        ]
    return []
