"""Narrow Django delivery boundary for runtime media formerly exposed by Apache."""

import mimetypes
from pathlib import Path, PurePosixPath

from django.conf import settings
from django.db import models
from django.http import FileResponse, Http404
from django.views.decorators.http import require_GET

from dotykacka.models import TenantBrand


PUBLIC_IMAGE_SUFFIXES = {".gif", ".jpeg", ".jpg", ".png", ".webp"}
SUPERUSER_PREFIXES = ("cards/", "cropped_images/", "output_passes/", "tenants/")


def _normalized_media_path(raw_path):
    candidate = PurePosixPath(str(raw_path or ""))
    if candidate.is_absolute() or not candidate.parts or any(
        part in {"", ".", ".."} for part in candidate.parts
    ):
        raise Http404
    root = Path(settings.MEDIA_ROOT).resolve()
    path = (root / Path(*candidate.parts)).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise Http404 from exc
    return candidate.as_posix(), path


def _is_public_brand_image(storage_name):
    if Path(storage_name).suffix.lower() not in PUBLIC_IMAGE_SUFFIXES:
        return False
    return TenantBrand.objects.filter(
        tenant__is_active=True,
    ).filter(
        models.Q(logo_path=storage_name)
        | models.Q(background_image_path=storage_name)
    ).exists()


@require_GET
def protected_media(request, path):
    storage_name, resolved_path = _normalized_media_path(path)
    is_public = _is_public_brand_image(storage_name)
    is_superuser_asset = bool(
        request.user.is_authenticated
        and request.user.is_active
        and request.user.is_superuser
        and storage_name.startswith(SUPERUSER_PREFIXES)
    )
    if not is_public and not is_superuser_asset:
        raise Http404
    if not resolved_path.is_file():
        raise Http404
    content_type = mimetypes.guess_type(resolved_path.name)[0] or "application/octet-stream"
    response = FileResponse(
        resolved_path.open("rb"),
        content_type=content_type,
        as_attachment=resolved_path.suffix.lower() == ".pkpass",
        filename=resolved_path.name,
    )
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = (
        "public, max-age=3600" if is_public else "private, no-store"
    )
    return response

__all__ = ["protected_media"]
