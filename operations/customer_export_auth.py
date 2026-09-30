"""Bearer-token authentication for the tenant-scoped customer export API."""

from functools import wraps

from django.conf import settings
from django.http import JsonResponse
from django.utils import timezone

from customers.models import CustomerExportApiToken
from operations.rate_limits import consume_rate_limit, request_identity


def _error_response(detail, *, status, retry_after=None):
    response = JsonResponse({"detail": detail}, status=status)
    response["Cache-Control"] = "no-store"
    if retry_after is not None:
        response["Retry-After"] = str(retry_after)
    return response


def _rate_limit(*, scope, identity, limit):
    allowed, retry_after = consume_rate_limit(
        scope=scope,
        identity=identity,
        limit=limit,
        window_seconds=settings.CUSTOMER_EXPORT_API_RATE_LIMIT_WINDOW_SECONDS,
    )
    if allowed:
        return None
    return _error_response(
        "Too many requests. Try again later.",
        status=429,
        retry_after=retry_after,
    )


def authenticate_bearer_token(request):
    authorization = request.headers.get("Authorization", "")
    scheme, separator, raw_token = authorization.partition(" ")
    if separator != " " or scheme.lower() != "bearer":
        return None

    raw_token = raw_token.strip()
    if (
        not raw_token.startswith(CustomerExportApiToken.TOKEN_PREFIX)
        or len(raw_token) > 200
    ):
        return None

    token = (
        CustomerExportApiToken.objects.select_related("tenant")
        .filter(
            token_hash=CustomerExportApiToken.digest(raw_token),
            revoked_at__isnull=True,
            tenant__is_active=True,
        )
        .first()
    )
    if token is None:
        return None

    used_at = timezone.now()
    CustomerExportApiToken.objects.filter(pk=token.pk).update(last_used_at=used_at)
    token.last_used_at = used_at
    return token


def customer_export_token_required(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        limited = _rate_limit(
            scope="customer_export.ip",
            identity=request_identity(request, extra="customer_export"),
            limit=settings.CUSTOMER_EXPORT_API_IP_RATE_LIMIT,
        )
        if limited is not None:
            return limited

        token = authenticate_bearer_token(request)
        if token is None:
            response = _error_response(
                "Missing, invalid, or revoked API token.",
                status=401,
            )
            response["WWW-Authenticate"] = 'Bearer realm="customer-export"'
            return response

        limited = _rate_limit(
            scope="customer_export.token",
            identity=f"token:{token.pk}",
            limit=settings.CUSTOMER_EXPORT_API_TOKEN_RATE_LIMIT,
        )
        if limited is not None:
            return limited

        request.customer_export_api_token = token
        return view(request, *args, **kwargs)

    return wrapped
