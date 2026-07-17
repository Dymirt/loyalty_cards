import hashlib
import json
import re
from uuid import NAMESPACE_URL, uuid5

from django.db import migrations


def _checksum(values):
    payload = json.dumps(values, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def backfill_card_designs(apps, schema_editor):
    Tenant = apps.get_model("dotykacka", "Tenant")
    TenantBrandRevision = apps.get_model("dotykacka", "TenantBrandRevision")
    CardDesign = apps.get_model("dotykacka", "CardDesign")
    CardBatch = apps.get_model("dotykacka", "CardBatch")
    IntegrationConnection = apps.get_model("dotykacka", "IntegrationConnection")
    PhysicalCard = apps.get_model("dotykacka", "PhysicalCard")
    WalletPass = apps.get_model("dotykacka", "WalletPass")

    for tenant in Tenant.objects.all().iterator():
        brand = tenant.brand
        brand_values = {
            "public_name": brand.public_name,
            "tagline": brand.tagline,
            "address": brand.address,
            "phone": brand.phone,
            "email": brand.email,
            "website_url": brand.website_url,
            "email_subject": brand.email_subject,
            "email_signature": brand.email_signature,
            "marketing_consent_text": brand.marketing_consent_text,
        }
        brand_revision, _ = TenantBrandRevision.objects.get_or_create(
            tenant=tenant,
            version=1,
            defaults={**brand_values, "snapshot_checksum": _checksum(brand_values)},
        )

        is_marta = tenant.slug == "marta-banaszek-atelier-cafe"
        design_values = {
            "name": "Marta legacy design" if is_marta else f"{tenant.name} initial design",
            "background_source": (
                "Marta Banaszek - Obraz II.jpg"
                if is_marta
                else brand.background_image_path
            ),
            "logo": brand.logo_path,
            "layout_preset": "marta_legacy" if is_marta else "centered",
            "crop_mode": "deterministic",
            "focal_x": 50,
            "focal_y": 50,
            "width_px": 1011,
            "height_px": 638,
            "dpi": 300,
            "bleed_mm": "0.0",
            "logo_width_px": 576,
            "front_text": brand.tagline,
            "back_text": "\n".join(
                value
                for value in (
                    brand.address,
                    f"tel.: {brand.phone}" if brand.phone else "",
                    f"e-mail: {brand.email}" if brand.email else "",
                )
                if value
            ),
            "foreground_color": "#000000",
            "panel_color": "#FFFFFF",
            "barcode_foreground_color": "#000000",
            "barcode_background_color": "#FFFFFF",
            "font_family": "barlow",
        }
        design, _ = CardDesign.objects.get_or_create(
            tenant=tenant,
            version=1,
            defaults={
                "brand_revision": brand_revision,
                **design_values,
                "design_checksum": _checksum(design_values),
            },
        )
        CardBatch.objects.filter(tenant=tenant, design__isnull=True).update(design=design)

        google_connection = IntegrationConnection.objects.filter(
            tenant=tenant,
            provider="google_wallet",
        ).first()
        issuer_id = (google_connection.configuration.get("issuer_id", "") if google_connection else "")
        cards_by_customer = {
            card.customer_id: card
            for card in PhysicalCard.objects.filter(
                tenant=tenant,
                customer__isnull=False,
            )
        }
        for customer in tenant.customers.all().iterator():
            safe_customer_id = re.sub(r"[^A-Za-z0-9._-]", "_", customer.klient_id)
            WalletPass.objects.get_or_create(
                customer=customer,
                defaults={
                    "tenant": tenant,
                    "physical_card": cards_by_customer.get(customer.pk),
                    "apple_serial": uuid5(
                        NAMESPACE_URL,
                        f"loyalty:{tenant.slug}:{customer.klient_id}",
                    ),
                    "google_object_id": (
                        f"{issuer_id}.{safe_customer_id}" if issuer_id else None
                    ),
                    "google_save_url": customer.google_jwt_url or "",
                    "apple_pass_path": (
                        cards_by_customer[customer.pk].apple_pass_path
                        if customer.pk in cards_by_customer
                        else ""
                    ),
                },
            )


class Migration(migrations.Migration):
    dependencies = [("dotykacka", "0012_card_design_foundation")]
    operations = [
        migrations.RunPython(
            backfill_card_designs,
            reverse_code=migrations.RunPython.noop,
        )
    ]
