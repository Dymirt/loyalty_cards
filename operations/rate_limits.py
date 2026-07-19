"""Database-backed rate limiting shared by every Apache worker process."""

import hashlib
import hmac
import logging
from datetime import UTC, datetime
from ipaddress import ip_address, ip_network

from django.conf import settings
from django.db import transaction
from django.http import HttpResponse
from django.utils import timezone

from .models import RateLimitBucket


logger = logging.getLogger("loyalty.security")


def _window_start(now, window_seconds):
    epoch = int(now.timestamp())
    return datetime.fromtimestamp(
        epoch - (epoch % window_seconds),
        tz=UTC,
    )


def _identity_hash(identity):
    return hmac.new(
        settings.SECRET_KEY.encode("utf-8"),
        identity.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _client_address(request):
    raw_remote = request.META.get("REMOTE_ADDR", "")
    try:
        remote_address = ip_address(raw_remote)
    except ValueError:
        return "unknown"
    trusted_networks = []
    for value in settings.LOYALTY_TRUSTED_PROXY_CIDRS:
        try:
            trusted_networks.append(ip_network(value, strict=False))
        except ValueError:
            continue
    if not any(remote_address in network for network in trusted_networks):
        return str(remote_address)
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    chain = []
    for value in forwarded.split(","):
        try:
            chain.append(ip_address(value.strip()))
        except ValueError:
            return str(remote_address)
    for candidate in reversed(chain):
        if not any(candidate in network for network in trusted_networks):
            return str(candidate)
    return str(remote_address)


def request_identity(request, *, extra=""):
    remote_address = _client_address(request)
    user_id = (
        str(request.user.pk)
        if getattr(request, "user", None) and request.user.is_authenticated
        else "anonymous"
    )
    return f"ip:{remote_address}|user:{user_id}|{extra}"


@transaction.atomic
def consume_rate_limit(*, scope, identity, limit, window_seconds, now=None):
    if limit <= 0 or window_seconds <= 0:
        raise ValueError("Rate-limit values must be positive.")
    now = now or timezone.now()
    window_started_at = _window_start(now, window_seconds)
    bucket, _created = RateLimitBucket.objects.get_or_create(
        scope=scope,
        identity_hash=_identity_hash(identity),
        window_started_at=window_started_at,
    )
    bucket = RateLimitBucket.objects.select_for_update().get(pk=bucket.pk)
    bucket.request_count += 1
    allowed = bucket.request_count <= limit
    if not allowed:
        bucket.limited_count += 1
    bucket.save(update_fields=("request_count", "limited_count", "updated_at"))
    retry_after = max(
        1,
        int(window_seconds - (now - window_started_at).total_seconds()),
    )
    return allowed, retry_after


def rate_limit_response(request, *, scope, limit, window_seconds, extra_identity=""):
    allowed, retry_after = consume_rate_limit(
        scope=scope,
        identity=request_identity(request, extra=extra_identity),
        limit=limit,
        window_seconds=window_seconds,
    )
    if allowed:
        return None
    logger.warning(
        "rate_limit.exceeded",
        extra={
            "request_id": getattr(request, "request_id", ""),
            "method": request.method,
            "path": request.path,
            "scope": scope,
            "event": "rate_limit.exceeded",
        },
    )
    response = HttpResponse(
        "Zbyt wiele prób. Spróbuj ponownie później.",
        status=429,
        content_type="text/plain; charset=utf-8",
    )
    response["Retry-After"] = str(retry_after)
    response["Cache-Control"] = "no-store"
    return response


__all__ = [
    "consume_rate_limit",
    "rate_limit_response",
    "request_identity",
]
