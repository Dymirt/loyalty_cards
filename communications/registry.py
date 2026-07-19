"""Optional enrollment-owned context provider without reversing dependencies."""

from dataclasses import dataclass, field
from typing import Callable


@dataclass(frozen=True)
class EmailApplicationContext:
    application_link_url: str = ""
    brand_snapshot: dict = field(default_factory=dict)
    generation: int = 1


_context_resolver: Callable[[object], EmailApplicationContext] | None = None


def register_email_application_context_resolver(resolver):
    global _context_resolver
    _context_resolver = resolver


def email_application_context(job):
    if _context_resolver is None:
        return EmailApplicationContext()
    return _context_resolver(job)


__all__ = [
    "EmailApplicationContext",
    "email_application_context",
    "register_email_application_context_resolver",
]
