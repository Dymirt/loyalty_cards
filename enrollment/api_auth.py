"""Bearer authentication limited to tenant virtual-card issuance."""

from functools import wraps

from django.conf import settings
from django.http import JsonResponse
from django.utils import timezone

from operations.rate_limits import consume_rate_limit, request_identity

from .models import VirtualCardApiKey


def api_error(detail, *, status, code, retry_after=None):
    response = JsonResponse({"error": {"code": code, "detail": detail}}, status=status)
    response["Cache-Control"] = "no-store"
    if retry_after is not None:
        response["Retry-After"] = str(retry_after)
    return response


def _rate_limit(*, scope, identity, limit):
    allowed, retry_after = consume_rate_limit(
        scope=scope,
        identity=identity,
        limit=limit,
        window_seconds=settings.VIRTUAL_CARD_API_RATE_LIMIT_WINDOW_SECONDS,
    )
    if allowed:
        return None
    return api_error(
        "Too many requests. Try again later.",
        status=429,
        code="rate_limited",
        retry_after=retry_after,
    )


def authenticate_virtual_card_key(request):
    authorization = request.headers.get("Authorization", "")
    scheme, separator, raw_token = authorization.partition(" ")
    if separator != " " or scheme.lower() != "bearer":
        return None
    raw_token = raw_token.strip()
    if not raw_token.startswith(VirtualCardApiKey.TOKEN_PREFIX) or len(raw_token) > 200:
        return None
    key = (
        VirtualCardApiKey.objects.select_related("tenant__brand")
        .filter(
            token_hash=VirtualCardApiKey.digest(raw_token),
            revoked_at__isnull=True,
            tenant__is_active=True,
        )
        .first()
    )
    if key is None:
        return None
    used_at = timezone.now()
    VirtualCardApiKey.objects.filter(pk=key.pk).update(last_used_at=used_at)
    key.last_used_at = used_at
    return key


def virtual_card_key_required(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        limited = _rate_limit(
            scope="virtual_card_api.ip",
            identity=request_identity(request, extra="virtual_card_api"),
            limit=settings.VIRTUAL_CARD_API_IP_RATE_LIMIT,
        )
        if limited is not None:
            return limited
        key = authenticate_virtual_card_key(request)
        if key is None:
            response = api_error(
                "Missing, invalid, or revoked API key.",
                status=401,
                code="invalid_api_key",
            )
            response["WWW-Authenticate"] = 'Bearer realm="virtual-cards"'
            return response
        limited = _rate_limit(
            scope="virtual_card_api.key",
            identity=f"key:{key.pk}",
            limit=settings.VIRTUAL_CARD_API_TOKEN_RATE_LIMIT,
        )
        if limited is not None:
            return limited
        request.virtual_card_api_key = key
        return view(request, *args, **kwargs)

    return wrapped


__all__ = [
    "api_error",
    "authenticate_virtual_card_key",
    "virtual_card_key_required",
]
