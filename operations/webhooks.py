"""Reusable replay-bounded HMAC verification for future provider webhooks."""

import hashlib
import hmac
import time


class WebhookSignatureError(ValueError):
    pass


def verify_signed_webhook(
    *,
    body,
    signature,
    timestamp,
    secret,
    tolerance_seconds=300,
    now=None,
):
    if not secret:
        raise WebhookSignatureError("Webhook secret is not configured.")
    try:
        timestamp_value = int(timestamp)
    except (TypeError, ValueError) as exc:
        raise WebhookSignatureError("Webhook timestamp is invalid.") from exc
    current = int(time.time() if now is None else now)
    if abs(current - timestamp_value) > tolerance_seconds:
        raise WebhookSignatureError("Webhook timestamp is outside the replay window.")
    supplied = str(signature or "")
    if supplied.startswith("sha256="):
        supplied = supplied[7:]
    signed_payload = str(timestamp_value).encode("ascii") + b"." + bytes(body)
    expected = hmac.new(
        secret.encode("utf-8"),
        signed_payload,
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(supplied, expected):
        raise WebhookSignatureError("Webhook signature is invalid.")
    return True


__all__ = ["WebhookSignatureError", "verify_signed_webhook"]
