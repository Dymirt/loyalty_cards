"""Read-only public tenant projection for the registration directory."""

from dataclasses import dataclass

from .models import Tenant


@dataclass(frozen=True)
class PublicRegistrationProgram:
    slug: str
    name: str
    tagline: str
    logo_path: str


def public_registration_programs():
    rows = (
        Tenant.objects.filter(
            is_active=True,
            public_registration_enabled=True,
            brand__isnull=False,
        )
        .values(
            "slug",
            "name",
            "brand__public_name",
            "brand__tagline",
            "brand__logo_path",
        )
        .order_by("brand__public_name", "name", "pk")
    )
    return tuple(
        PublicRegistrationProgram(
            slug=row["slug"],
            name=row["brand__public_name"] or row["name"],
            tagline=row["brand__tagline"] or "",
            logo_path=row["brand__logo_path"] or "",
        )
        for row in rows
    )


__all__ = ["PublicRegistrationProgram", "public_registration_programs"]
