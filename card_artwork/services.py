"""Deterministic tenant card rendering and immutable artifact services."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import barcode
from barcode.writer import ImageWriter
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Max
from django.utils.translation import gettext as _
from PIL import Image, ImageDraw, ImageFont, ImageOps

from cards.models import PhysicalCard
from dotykacka.models import AuditEvent
from tenants.models import Tenant, TenantBrand, TenantBrandRevision

from .models import CardArtifact, CardDesign, CropPlan


RENDER_VERSION = "card-artwork-v1"


@dataclass(frozen=True)
class DesignSpec:
    tenant_slug: str
    card_prefix: str
    name: str
    layout_preset: str
    crop_mode: str
    focal_x: int
    focal_y: int
    width_px: int
    height_px: int
    dpi: int
    bleed_mm: str
    logo_width_px: int
    front_text: str
    back_text: str
    foreground_color: str
    panel_color: str
    barcode_foreground_color: str
    barcode_background_color: str
    font_family: str
    checksum: str
    background_bytes: bytes = b""
    logo_bytes: bytes = b""


@dataclass(frozen=True)
class CropPlanData:
    card_code: str
    seed: str
    source_sha256: str
    source_width: int
    source_height: int
    resized_width: int
    resized_height: int
    crop_left: int
    crop_top: int
    crop_right: int
    crop_bottom: int
    render_version: str = RENDER_VERSION

    @property
    def crop_box(self):
        return (self.crop_left, self.crop_top, self.crop_right, self.crop_bottom)

    def metadata(self):
        return asdict(self)


@dataclass(frozen=True)
class RenderedCard:
    front: bytes
    back: bytes
    barcode: bytes
    crop_box: tuple[int, int, int, int] | None
    width_px: int
    height_px: int
    dpi: int
    crop_plan: CropPlanData | None = None

    def data_urls(self):
        return {
            "front": _data_url(self.front, "image/jpeg"),
            "back": _data_url(self.back, "image/jpeg"),
            "barcode": _data_url(self.barcode, "image/png"),
        }


def canonical_checksum(values):
    payload = json.dumps(
        values,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def bytes_sha256(content):
    return hashlib.sha256(content).hexdigest()


def _data_url(content, mime_type):
    return f"data:{mime_type};base64,{base64.b64encode(content).decode('ascii')}"


def _read_file(value):
    if not value:
        return b""
    if hasattr(value, "open"):
        value.open("rb")
    try:
        content = value.read()
        if hasattr(value, "seek"):
            value.seek(0)
    finally:
        if hasattr(value, "close"):
            value.close()
    return content


def _read_upload(value):
    if not value:
        return b""
    value.seek(0)
    content = value.read()
    value.seek(0)
    return content


def _brand_back_text(brand_values):
    return "\n".join(
        value
        for value in (
            brand_values.get("address", ""),
            brand_values.get("phone", ""),
            brand_values.get("website_url", ""),
        )
        if value
    )


def apply_brand_defaults(brand_values, design_values):
    """Apply the published brand when optional card text is not overridden."""

    values = dict(design_values)
    values["front_text"] = values.get("front_text") or brand_values.get("tagline") or brand_values.get("public_name", "")
    values["back_text"] = values.get("back_text") or _brand_back_text(brand_values)
    return values


def spec_from_design(design):
    return DesignSpec(
        tenant_slug=design.tenant.slug,
        card_prefix=design.tenant.card_prefix,
        name=design.name,
        layout_preset=design.layout_preset,
        crop_mode=design.crop_mode,
        focal_x=design.focal_x,
        focal_y=design.focal_y,
        width_px=design.width_px,
        height_px=design.height_px,
        dpi=design.dpi,
        bleed_mm=str(design.bleed_mm),
        logo_width_px=design.logo_width_px,
        front_text=design.front_text,
        back_text=design.back_text,
        foreground_color=design.foreground_color,
        panel_color=design.panel_color,
        barcode_foreground_color=design.barcode_foreground_color,
        barcode_background_color=design.barcode_background_color,
        font_family=design.font_family,
        checksum=design.design_checksum,
        background_bytes=_read_file(design.background_source),
        logo_bytes=_read_file(design.logo),
    )


def spec_from_values(*, tenant, values, background_upload=None, logo_upload=None, fallback_design=None):
    background_bytes = _read_upload(background_upload)
    logo_bytes = _read_upload(logo_upload)
    if fallback_design:
        if not background_bytes:
            background_bytes = _read_file(fallback_design.background_source)
        if not logo_bytes:
            logo_bytes = _read_file(fallback_design.logo)
    checksum_values = {
        **values,
        "background_sha256": bytes_sha256(background_bytes) if background_bytes else "",
        "logo_sha256": bytes_sha256(logo_bytes) if logo_bytes else "",
    }
    return DesignSpec(
        tenant_slug=tenant.slug,
        card_prefix=tenant.card_prefix,
        name=values["name"],
        layout_preset=values["layout_preset"],
        crop_mode=values["crop_mode"],
        focal_x=values["focal_x"],
        focal_y=values["focal_y"],
        width_px=values["width_px"],
        height_px=values["height_px"],
        dpi=values["dpi"],
        bleed_mm=str(values["bleed_mm"]),
        logo_width_px=values["logo_width_px"],
        front_text=values.get("front_text", ""),
        back_text=values.get("back_text", ""),
        foreground_color=values["foreground_color"],
        panel_color=values["panel_color"],
        barcode_foreground_color=values["barcode_foreground_color"],
        barcode_background_color=values["barcode_background_color"],
        font_family=values["font_family"],
        checksum=canonical_checksum(checksum_values),
        background_bytes=background_bytes,
        logo_bytes=logo_bytes,
    )


def _font_path(bold=True):
    filename = "Barlow-Bold.ttf" if bold else "Barlow-Medium.ttf"
    return Path(settings.BASE_DIR) / "static" / "fonts" / "Barlow" / filename


def _font(size, *, bold=True):
    path = _font_path(bold=bold)
    if path.is_file():
        return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default(size=size)


def calculate_crop_plan(spec, card_code):
    seed = hashlib.sha256(f"{spec.checksum}:{card_code}".encode("utf-8")).hexdigest()
    if not spec.background_bytes:
        return CropPlanData(
            card_code=card_code,
            seed=seed,
            source_sha256="",
            source_width=spec.width_px,
            source_height=spec.height_px,
            resized_width=spec.width_px,
            resized_height=spec.height_px,
            crop_left=0,
            crop_top=0,
            crop_right=spec.width_px,
            crop_bottom=spec.height_px,
        )
    with Image.open(BytesIO(spec.background_bytes)) as opened:
        source = ImageOps.exif_transpose(opened)
        source_width, source_height = source.size
    scale = max(spec.width_px / source_width, spec.height_px / source_height)
    resized_width = round(source_width * scale)
    resized_height = round(source_height * scale)
    max_left = max(0, resized_width - spec.width_px)
    max_top = max(0, resized_height - spec.height_px)
    digest = bytes.fromhex(seed)
    if spec.crop_mode == CardDesign.CropMode.DETERMINISTIC:
        left = int.from_bytes(digest[:4], "big") % (max_left + 1)
        top = int.from_bytes(digest[4:8], "big") % (max_top + 1)
    elif spec.crop_mode == CardDesign.CropMode.FOCAL:
        left = round(max_left * spec.focal_x / 100)
        top = round(max_top * spec.focal_y / 100)
    else:
        left = max_left // 2
        top = max_top // 2
    return CropPlanData(
        card_code=card_code,
        seed=seed,
        source_sha256=bytes_sha256(spec.background_bytes),
        source_width=source_width,
        source_height=source_height,
        resized_width=resized_width,
        resized_height=resized_height,
        crop_left=left,
        crop_top=top,
        crop_right=left + spec.width_px,
        crop_bottom=top + spec.height_px,
    )


def _cover_background(spec, plan):
    if not spec.background_bytes:
        return Image.new("RGB", (spec.width_px, spec.height_px), spec.panel_color)
    with Image.open(BytesIO(spec.background_bytes)) as opened:
        source = ImageOps.exif_transpose(opened).convert("RGB")
    resized = source.resize(
        (plan.resized_width, plan.resized_height),
        Image.Resampling.LANCZOS,
    )
    return resized.crop(plan.crop_box)


def _add_logo(image, spec, *, front):
    if not spec.logo_bytes:
        return
    with Image.open(BytesIO(spec.logo_bytes)) as opened:
        logo = ImageOps.exif_transpose(opened).convert("RGBA")
    target_width = min(spec.logo_width_px, max(1, image.width - 100))
    target_height = max(1, round(logo.height * target_width / logo.width))
    logo = logo.resize((target_width, target_height), Image.Resampling.LANCZOS)
    if spec.layout_preset == CardDesign.LayoutPreset.MARTA_LEGACY and front:
        position = (50, 50)
    else:
        position = ((image.width - target_width) // 2, 50)
    image.paste(logo, position, logo)


def _fit_font(draw, text, max_width, preferred_size, minimum_size=18):
    for size in range(preferred_size, minimum_size - 1, -2):
        font = _font(size)
        bbox = draw.multiline_textbbox((0, 0), text, font=font, align="center", spacing=8)
        if bbox[2] - bbox[0] <= max_width:
            return font
    return _font(minimum_size)


def _add_front_text(image, spec):
    if not spec.front_text:
        return
    draw = ImageDraw.Draw(image)
    font = _fit_font(draw, spec.front_text, image.width - 80, 60)
    bbox = draw.textbbox((0, 0), spec.front_text, font=font)
    width = bbox[2] - bbox[0]
    height = bbox[3] - bbox[1]
    draw.text(
        ((image.width - width) / 2, image.height - height - 28),
        spec.front_text,
        font=font,
        fill=spec.foreground_color,
    )


def _add_back_text(image, spec):
    if not spec.back_text:
        return
    draw = ImageDraw.Draw(image)
    font = _fit_font(draw, spec.back_text, image.width - 80, 40)
    bbox = draw.multiline_textbbox((0, 0), spec.back_text, font=font, align="center", spacing=6)
    width = bbox[2] - bbox[0]
    height = bbox[3] - bbox[1]
    x = (image.width - width) / 2
    y = (image.height - height) / 2 - 30
    padding = 12
    draw.rectangle((x - padding, y - padding, x + width + padding, y + height + padding), fill=spec.panel_color)
    draw.multiline_text((x, y), spec.back_text, font=font, fill=spec.foreground_color, align="center", spacing=6)


def _barcode_png(card_code, spec):
    stream = BytesIO()
    code128 = barcode.get("code128", card_code, writer=ImageWriter())
    code128.write(
        stream,
        {
            "module_height": 5,
            "font_size": 3,
            "text_distance": 2,
            "background": spec.barcode_background_color,
            "foreground": spec.barcode_foreground_color,
            "quiet_zone": 1,
            "font_path": str(_font_path(bold=False)),
            "dpi": spec.dpi,
        },
    )
    return stream.getvalue()


def _add_barcode(image, barcode_png):
    with Image.open(BytesIO(barcode_png)) as opened:
        barcode_image = opened.convert("RGB")
    if barcode_image.height > 10:
        barcode_image = barcode_image.crop((0, 0, barcode_image.width, barcode_image.height - 10))
    target = (round(barcode_image.width * 1.5), round(barcode_image.height * 1.5))
    barcode_image = barcode_image.resize(target, Image.Resampling.LANCZOS)
    position = ((image.width - target[0]) // 2, image.height - target[1] - 50)
    image.paste(barcode_image, position)


def _jpeg_bytes(image, dpi):
    stream = BytesIO()
    image.convert("RGB").save(
        stream,
        format="JPEG",
        quality=90,
        subsampling=0,
        optimize=False,
        dpi=(dpi, dpi),
    )
    return stream.getvalue()


def render_card(spec, card_code, *, crop_plan=None):
    plan = crop_plan or calculate_crop_plan(spec, card_code)
    if plan.card_code != card_code:
        raise ValidationError(_("Plan kadrowania nie odpowiada kodowi renderowanej karty."))
    background = _cover_background(spec, plan)
    front = background.copy()
    back = ImageOps.mirror(background)
    _add_logo(front, spec, front=True)
    _add_front_text(front, spec)
    _add_logo(back, spec, front=False)
    _add_back_text(back, spec)
    barcode_png = _barcode_png(card_code, spec)
    _add_barcode(back, barcode_png)
    rendered = RenderedCard(
        front=_jpeg_bytes(front, spec.dpi),
        back=_jpeg_bytes(back, spec.dpi),
        barcode=barcode_png,
        crop_box=plan.crop_box,
        width_px=spec.width_px,
        height_px=spec.height_px,
        dpi=spec.dpi,
        crop_plan=plan,
    )
    validate_rendered_card(rendered)
    return rendered


def validate_rendered_card(rendered):
    for content in (rendered.front, rendered.back):
        with Image.open(BytesIO(content)) as image:
            if image.size != (rendered.width_px, rendered.height_px):
                raise ValidationError(_("Wymiary wygenerowanej karty nie odpowiadają projektowi."))
    if not rendered.barcode.startswith(b"\x89PNG"):
        raise ValidationError(_("Generator kodu nie utworzył pliku PNG."))


def build_sample_sheet(spec, *, count=6):
    """Return deterministic varied branded samples without persisting a draft."""

    samples = []
    for number in range(1, count + 1):
        card_code = f"{spec.card_prefix}-{number}"
        rendered = render_card(spec, card_code)
        samples.append(
            {
                "card_code": card_code,
                "front": rendered.data_urls()["front"],
                "crop_box": rendered.crop_box,
                "crop_plan": rendered.crop_plan.metadata(),
                "front_sha256": bytes_sha256(rendered.front),
            }
        )
    return samples


def brand_snapshot_values(values):
    fields = (
        "public_name",
        "tagline",
        "address",
        "phone",
        "email",
        "website_url",
        "email_subject",
        "email_signature",
        "marketing_consent_text",
    )
    return {field: values.get(field, "") for field in fields}


def design_snapshot_values(values):
    fields = (
        "name",
        "layout_preset",
        "crop_mode",
        "focal_x",
        "focal_y",
        "width_px",
        "height_px",
        "dpi",
        "bleed_mm",
        "logo_width_px",
        "front_text",
        "back_text",
        "foreground_color",
        "panel_color",
        "barcode_foreground_color",
        "barcode_background_color",
        "font_family",
    )
    return {field: values.get(field, "") for field in fields}


@transaction.atomic
def publish_card_design(*, tenant, actor, brand_values, design_values, background_upload=None, logo_upload=None):
    locked_tenant = Tenant.objects.select_for_update().get(pk=tenant.pk)
    latest = CardDesign.objects.filter(tenant=locked_tenant).order_by("-version").first()
    version = (CardDesign.objects.filter(tenant=locked_tenant).aggregate(value=Max("version"))["value"] or 0) + 1
    brand_data = brand_snapshot_values(brand_values)
    design_data = apply_brand_defaults(brand_data, design_snapshot_values(design_values))
    spec = spec_from_values(
        tenant=locked_tenant,
        values=design_data,
        background_upload=background_upload,
        logo_upload=logo_upload,
        fallback_design=latest,
    )
    if CardDesign.objects.filter(tenant=locked_tenant, design_checksum=spec.checksum).exists():
        raise ValidationError(_("Ten projekt jest już opublikowany dla tej firmy."))
    brand_revision = TenantBrandRevision(
        tenant=locked_tenant,
        version=version,
        created_by=actor,
        snapshot_checksum=canonical_checksum(brand_data),
        **brand_data,
    )
    brand_revision.full_clean()
    brand_revision.save()
    design = CardDesign(
        tenant=locked_tenant,
        brand_revision=brand_revision,
        version=version,
        created_by=actor,
        design_checksum=spec.checksum,
        **design_data,
    )
    if background_upload:
        design.background_source = background_upload
    elif latest and latest.background_source:
        design.background_source.name = latest.background_source.name
    if logo_upload:
        design.logo = logo_upload
    elif latest and latest.logo:
        design.logo.name = latest.logo.name
    design.full_clean()
    try:
        design.save()
    except IntegrityError as exc:
        raise ValidationError(_("Równoczesna publikacja utworzyła już tę wersję projektu.")) from exc
    current_brand, _ = TenantBrand.objects.get_or_create(tenant=locked_tenant, defaults=brand_data)
    for field, value in brand_data.items():
        setattr(current_brand, field, value)
    current_brand.logo_path = design.logo.name
    current_brand.background_image_path = design.background_source.name
    current_brand.save()
    return design


def get_or_create_crop_plan(*, design, card_code, physical_card=None):
    spec = spec_from_design(design)
    data = calculate_crop_plan(spec, card_code)
    existing = CropPlan.objects.filter(
        design=design,
        card_code=card_code,
        render_version=RENDER_VERSION,
    ).first()
    if existing:
        stored = {field: getattr(existing, field) for field in data.metadata()}
        if stored != data.metadata():
            raise ValidationError(_("Zapisany plan kadrowania nie odpowiada danym wejściowym."))
        return existing, data
    plan = CropPlan(
        tenant=design.tenant,
        design=design,
        physical_card=physical_card,
        **data.metadata(),
    )
    plan.full_clean()
    try:
        plan.save()
    except IntegrityError:
        plan = CropPlan.objects.get(
            design=design,
            card_code=card_code,
            render_version=RENDER_VERSION,
        )
    return plan, data


def _artifact_root(design, batch_id, run_id, card_code):
    safe_code = card_code.replace("/", "_").replace("\\", "_")
    batch_segment = f"batch-{batch_id}" if batch_id else "proofs"
    return Path(
        f"tenants/{design.tenant.slug}/designs/v{design.version:04d}/"
        f"{batch_segment}/runs/{run_id}/cards/{safe_code}"
    )


def _publish_files(relative_root, files):
    media_root = Path(settings.MEDIA_ROOT).resolve()
    final_root = (media_root / relative_root).resolve()
    if media_root not in final_root.parents:
        raise ValidationError(_("Niedozwolona ścieżka pliku."))
    final_root.parent.mkdir(parents=True, exist_ok=True)
    temporary_root = Path(tempfile.mkdtemp(prefix=".generating-", dir=final_root.parent))
    try:
        for filename, content in files.items():
            (temporary_root / filename).write_bytes(content)
        os.replace(temporary_root, final_root)
    except Exception:
        if temporary_root.exists():
            for path in temporary_root.iterdir():
                path.unlink()
            temporary_root.rmdir()
        raise


def _create_artifacts(*, design, relative_root, files, kinds, crop_plan, batch=None, physical_card=None):
    artifacts = []
    with transaction.atomic():
        for filename, content in files.items():
            artifact = CardArtifact(
                tenant=design.tenant,
                design=design,
                batch=batch,
                physical_card=physical_card,
                kind=kinds[filename],
                storage_path=str(relative_root / filename),
                sha256=bytes_sha256(content),
                size_bytes=len(content),
                metadata={
                    "run_id": relative_root.parts[-3],
                    "crop_box": crop_plan.crop_box,
                    "crop_plan_id": crop_plan.pk,
                    "render_version": crop_plan.render_version,
                },
            )
            artifact.full_clean()
            artifact.save()
            artifacts.append(artifact)
    return artifacts


def generate_proof_artifacts(*, design, card_code=None):
    card_code = card_code or f"{design.tenant.card_prefix}-1"
    crop_plan, plan_data = get_or_create_crop_plan(design=design, card_code=card_code)
    rendered = render_card(spec_from_design(design), card_code, crop_plan=plan_data)
    run_id = uuid4().hex
    relative_root = _artifact_root(design, None, run_id, card_code)
    files = {
        "proof-front.jpg": rendered.front,
        "proof-back.jpg": rendered.back,
        "barcode.png": rendered.barcode,
    }
    manifest = {
        "schema": "loyalty-card-proof/v2",
        "tenant": design.tenant.slug,
        "design_version": design.version,
        "design_checksum": design.design_checksum,
        "card_code": card_code,
        "crop_box": rendered.crop_box,
        "crop_plan": plan_data.metadata(),
        "width_px": rendered.width_px,
        "height_px": rendered.height_px,
        "dpi": rendered.dpi,
        "files": {name: bytes_sha256(content) for name, content in files.items()},
    }
    files["manifest.json"] = json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
    _publish_files(relative_root, files)
    kinds = {
        "proof-front.jpg": CardArtifact.Kind.PROOF_FRONT,
        "proof-back.jpg": CardArtifact.Kind.PROOF_BACK,
        "barcode.png": CardArtifact.Kind.BARCODE,
        "manifest.json": CardArtifact.Kind.MANIFEST,
    }
    return _create_artifacts(
        design=design,
        relative_root=relative_root,
        files=files,
        kinds=kinds,
        crop_plan=crop_plan,
    )


def publish_design_release(
    *,
    tenant,
    actor,
    brand_values,
    design_values,
    background_upload=None,
    logo_upload=None,
):
    """Publish, render the first proof, and append its redacted audit event."""

    design = publish_card_design(
        tenant=tenant,
        actor=actor,
        brand_values=brand_values,
        design_values=design_values,
        background_upload=background_upload,
        logo_upload=logo_upload,
    )
    generate_proof_artifacts(design=design)
    AuditEvent.objects.create(
        tenant=tenant,
        actor=actor,
        action="card_design.published",
        object_type="CardDesign",
        object_id=str(design.pk),
        metadata={"version": design.version, "checksum": design.design_checksum},
    )
    return design


def generate_card_artifacts(*, design, physical_card):
    if physical_card.tenant_id != design.tenant_id:
        raise ValidationError(_("Karta i projekt muszą należeć do tej samej firmy."))
    crop_plan, plan_data = get_or_create_crop_plan(
        design=design,
        card_code=physical_card.code,
        physical_card=physical_card,
    )
    rendered = render_card(spec_from_design(design), physical_card.code, crop_plan=plan_data)
    run_id = uuid4().hex
    relative_root = _artifact_root(design, physical_card.batch_id, run_id, physical_card.code)
    files = {"front.jpg": rendered.front, "back.jpg": rendered.back, "barcode.png": rendered.barcode}
    manifest = {
        "schema": "loyalty-card-artifacts/v2",
        "tenant": design.tenant.slug,
        "design_version": design.version,
        "design_checksum": design.design_checksum,
        "batch_id": physical_card.batch_id,
        "card_code": physical_card.code,
        "crop_box": rendered.crop_box,
        "crop_plan": plan_data.metadata(),
        "width_px": rendered.width_px,
        "height_px": rendered.height_px,
        "dpi": rendered.dpi,
        "files": {name: bytes_sha256(content) for name, content in files.items()},
    }
    files["manifest.json"] = json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
    _publish_files(relative_root, files)
    kinds = {
        "front.jpg": CardArtifact.Kind.CARD_FRONT,
        "back.jpg": CardArtifact.Kind.CARD_BACK,
        "barcode.png": CardArtifact.Kind.BARCODE,
        "manifest.json": CardArtifact.Kind.MANIFEST,
    }
    return _create_artifacts(
        design=design,
        relative_root=relative_root,
        files=files,
        kinds=kinds,
        crop_plan=crop_plan,
        batch=physical_card.batch,
        physical_card=physical_card,
    )


def resolve_artifact_path(artifact):
    media_root = Path(settings.MEDIA_ROOT).resolve()
    artifact_path = (media_root / artifact.storage_path).resolve()
    if media_root not in artifact_path.parents:
        raise ValidationError(_("Niedozwolona ścieżka pliku."))
    return artifact_path
