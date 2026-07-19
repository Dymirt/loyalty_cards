"""Request correlation, safe request summaries and browser security headers."""

import logging
import re
import time
from uuid import uuid4


logger = logging.getLogger("loyalty.request")
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._:-]{8,64}$")


class PlatformSecurityMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        started = time.monotonic()
        supplied_id = request.headers.get("X-Request-ID", "")
        request.request_id = (
            supplied_id if _SAFE_REQUEST_ID.fullmatch(supplied_id) else uuid4().hex
        )
        response = self.get_response(request)
        response["X-Request-ID"] = request.request_id
        response.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; base-uri 'self'; connect-src 'self'; "
            "font-src 'self'; form-action 'self'; frame-ancestors 'none'; "
            "img-src 'self' data: blob:; object-src 'none'; script-src 'self'; "
            "style-src 'self'",
        )
        response.setdefault(
            "Permissions-Policy",
            "camera=(self), geolocation=(), microphone=(), payment=(), usb=()",
        )
        if getattr(request, "user", None) and request.user.is_authenticated:
            response.setdefault("Cache-Control", "private, no-store")
        logger.info(
            "request.completed",
            extra={
                "request_id": request.request_id,
                "method": request.method,
                "path": request.path,
                "status_code": response.status_code,
                "duration_ms": round((time.monotonic() - started) * 1000, 2),
                "user_id": request.user.pk
                if getattr(request, "user", None) and request.user.is_authenticated
                else None,
                "event": "request.completed",
            },
        )
        return response


__all__ = ["PlatformSecurityMiddleware"]
