"""Secret-redacting structured logging without an external logging service."""

import json
import logging
import re
from datetime import UTC, datetime


_SENSITIVE_PAIR = re.compile(
    r"(?i)(authorization|api[_-]?key|client[_-]?secret|password|refresh[_-]?token|access[_-]?token|token)"
    r"([\s\"'=:\\]+)([^\s,;&\"']+)"
)
_SENSITIVE_QUERY = re.compile(
    r"(?i)([?&](?:authorization|api[_-]?key|client[_-]?secret|password|refresh[_-]?token|access[_-]?token|token)=)[^&\s]+"
)


def redact_text(value):
    text = str(value)
    text = _SENSITIVE_QUERY.sub(r"\1[REDACTED]", text)
    return _SENSITIVE_PAIR.sub(r"\1\2[REDACTED]", text)


class RedactingFilter(logging.Filter):
    def filter(self, record):
        if isinstance(record.msg, str):
            record.msg = redact_text(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {
                    key: "[REDACTED]"
                    if any(marker in key.lower() for marker in ("secret", "password", "token", "authorization", "api_key"))
                    else redact_text(value)
                    for key, value in record.args.items()
                }
            else:
                record.args = tuple(redact_text(value) for value in record.args)
        return True


class JsonLogFormatter(logging.Formatter):
    SAFE_FIELDS = (
        "request_id",
        "method",
        "path",
        "status_code",
        "duration_ms",
        "user_id",
        "scope",
        "event",
    )

    def format(self, record):
        payload = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact_text(record.getMessage()),
        }
        for field in self.SAFE_FIELDS:
            value = getattr(record, field, None)
            if value not in (None, ""):
                payload[field] = value
        if record.exc_info:
            payload["exception"] = redact_text(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


__all__ = ["JsonLogFormatter", "RedactingFilter", "redact_text"]
