import hashlib
import json

from django.db import migrations, models


MARTA_SLUG = "marta-banaszek-atelier-cafe"


def _checksum(values):
    payload = json.dumps(
        values,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def publish_marta_virtual_designs(apps, schema_editor):
    Tenant = apps.get_model("dotykacka", "Tenant")
    CardDesign = apps.get_model("dotykacka", "CardDesign")
    try:
        tenant = Tenant.objects.get(slug=MARTA_SLUG)
    except Tenant.DoesNotExist:
        return
    base = CardDesign.objects.filter(tenant=tenant).order_by("version").first()
    if base is None:
        return

    shared = {
        "brand_revision_id": base.brand_revision_id,
        "logo": base.logo.name,
        "width_px": base.width_px,
        "height_px": base.height_px,
        "dpi": base.dpi,
        "bleed_mm": base.bleed_mm,
        "logo_width_px": base.logo_width_px,
        "front_text": base.front_text,
        "back_text": base.back_text,
        "font_family": base.font_family,
    }
    catalog = (
        {
            "version": 2,
            "name": "Atelier Signature",
            "background_source": "Marta Banaszek - Obraz.jpg",
            "layout_preset": "marta_legacy",
            "crop_mode": "focal",
            "focal_x": 32,
            "focal_y": 50,
            "foreground_color": "#FFFFFF",
            "panel_color": "#171412",
            "barcode_foreground_color": "#171412",
            "barcode_background_color": "#FFFFFF",
        },
        {
            "version": 3,
            "name": "Café Crème",
            "background_source": "Marta Banaszek - Obraz II.jpg",
            "layout_preset": "centered",
            "crop_mode": "focal",
            "focal_x": 68,
            "focal_y": 50,
            "foreground_color": "#241A14",
            "panel_color": "#F2E6D4",
            "barcode_foreground_color": "#241A14",
            "barcode_background_color": "#F9F2E8",
        },
        {
            "version": 4,
            "name": "Fashion Rosé",
            "background_source": "Marta Banaszek - Obraz.jpg",
            "layout_preset": "centered",
            "crop_mode": "focal",
            "focal_x": 50,
            "focal_y": 34,
            "foreground_color": "#25191B",
            "panel_color": "#D7A5A8",
            "barcode_foreground_color": "#25191B",
            "barcode_background_color": "#F8ECEC",
        },
        {
            "version": 5,
            "name": "Atelier Monochrome",
            "background_source": "Marta Banaszek - Obraz II.jpg",
            "layout_preset": "marta_legacy",
            "crop_mode": "focal",
            "focal_x": 50,
            "focal_y": 66,
            "foreground_color": "#111111",
            "panel_color": "#FFFFFF",
            "barcode_foreground_color": "#111111",
            "barcode_background_color": "#FFFFFF",
        },
    )
    for variant in catalog:
        values = {**shared, **variant}
        checksum_values = {
            key: str(value) if key == "bleed_mm" else value
            for key, value in values.items()
            if key != "brand_revision_id"
        }
        CardDesign.objects.get_or_create(
            tenant=tenant,
            version=variant["version"],
            defaults={
                **values,
                "is_virtual_catalog": True,
                "design_checksum": _checksum(checksum_values),
            },
        )


class Migration(migrations.Migration):
    dependencies = [("dotykacka", "0017_walletpass_card_design")]
    operations = [
        migrations.AddField(
            model_name="carddesign",
            name="is_virtual_catalog",
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(
            publish_marta_virtual_designs,
            reverse_code=migrations.RunPython.noop,
        )
    ]
