import base64
import hashlib
import json
import re

from cryptography.fernet import Fernet
from django.conf import settings
from django.db import migrations


MARTA_SLUG = "marta-banaszek-atelier-cafe"


def _encryption_key():
    keys = getattr(settings, "TENANT_SECRETS_ENCRYPTION_KEYS", [])
    if keys:
        return keys[0].encode("ascii")
    digest = hashlib.sha256(settings.SECRET_KEY.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def _encrypt(credentials):
    cleaned = {key: value for key, value in credentials.items() if value}
    if not cleaned:
        return ""
    payload = json.dumps(cleaned, sort_keys=True).encode("utf-8")
    token = Fernet(_encryption_key()).encrypt(payload).decode("ascii")
    return f"fernet:v1:{token}"


def backfill_marta(apps, schema_editor):
    Tenant = apps.get_model("dotykacka", "Tenant")
    TenantBrand = apps.get_model("dotykacka", "TenantBrand")
    TenantMembership = apps.get_model("dotykacka", "TenantMembership")
    IntegrationConnection = apps.get_model("dotykacka", "IntegrationConnection")
    AccessToken = apps.get_model("dotykacka", "AccessToken")
    Klient = apps.get_model("dotykacka", "Klient")
    CardBatch = apps.get_model("dotykacka", "CardBatch")
    PhysicalCard = apps.get_model("dotykacka", "PhysicalCard")
    User = apps.get_model(*settings.AUTH_USER_MODEL.split("."))

    tenant, _ = Tenant.objects.get_or_create(
        slug=MARTA_SLUG,
        defaults={
            "name": "Marta Banaszek / Atelier-Café",
            "legal_name": "Centrum Concept Sp. z o.o. Marta Banaszek Atelier-Cafe",
            "card_prefix": "MB",
            "language_code": "pl-pl",
            "timezone": "Europe/Warsaw",
            "is_active": True,
            "public_registration_enabled": True,
        },
    )
    TenantBrand.objects.get_or_create(
        tenant=tenant,
        defaults={
            "public_name": "Atelier-Café Marta Banaszek",
            "tagline": "where coffee meets fashion",
            "address": "ul. Wąwozowa 8/lokal 3a, 02-796 Warszawa",
            "phone": "+48 519 727 253",
            "email": "concept@martabanaszek.pl",
            "website_url": "https://www.martabanaszek.pl",
            "logo_path": "logo_atelier_cafe.png",
            "background_image_path": "obraz_com.jpg",
            "email_subject": "Twoja karta gościa Atelier-Café Marta Banaszek",
            "email_signature": "Zespół Atelier-Café Marta Banaszek",
            "marketing_consent_text": (
                "Wyrażam zgodę na kontakt i przesyłanie treści marketingowych dla firmy "
                "Centrum Concept Sp. z o.o. Marta Banaszek Atelier-Cafe"
            ),
        },
    )

    dotykacka, dotykacka_created = IntegrationConnection.objects.get_or_create(
        tenant=tenant,
        provider="dotykacka",
        defaults={
            "configuration": {
                "cloud_id": getattr(settings, "DOTYKACKA_CLOUD_ID", 0),
                "discount_group_id": getattr(settings, "DOTYKACKA_DISCOUNT_GROUP_ID", 0),
            },
            "credentials_encrypted": _encrypt(
                {"authorization_token": getattr(settings, "DOTYKACKA_AUTHORIZATION_TOKEN", "")}
            ),
            "enabled": bool(
                getattr(settings, "DOTYKACKA_AUTHORIZATION_TOKEN", "")
                and getattr(settings, "DOTYKACKA_CLOUD_ID", 0)
                and getattr(settings, "DOTYKACKA_DISCOUNT_GROUP_ID", 0)
            ),
        },
    )
    if not dotykacka_created:
        dotykacka = IntegrationConnection.objects.get(pk=dotykacka.pk)

    IntegrationConnection.objects.get_or_create(
        tenant=tenant,
        provider="brevo",
        defaults={
            "configuration": {
                "list_id": getattr(settings, "BREVO_LIST_ID", 0),
                "default_phone_country_code": getattr(
                    settings, "DEFAULT_PHONE_COUNTRY_CODE", "+48"
                ),
            },
            "credentials_encrypted": _encrypt(
                {"api_key": getattr(settings, "BREVO_API_KEY", "")}
            ),
            "enabled": bool(
                getattr(settings, "BREVO_API_KEY", "")
                and getattr(settings, "BREVO_LIST_ID", 0)
            ),
        },
    )
    IntegrationConnection.objects.get_or_create(
        tenant=tenant,
        provider="google_wallet",
        defaults={
            "configuration": {
                "issuer_id": getattr(settings, "GOOGLE_WALLET_ISSUER_ID", ""),
                "class_suffix": getattr(settings, "GOOGLE_WALLET_CLASS_SUFFIX", "MB"),
            },
            "enabled": bool(getattr(settings, "GOOGLE_WALLET_ISSUER_ID", "")),
        },
    )

    for user_id in User.objects.values_list("pk", flat=True):
        TenantMembership.objects.get_or_create(
            tenant=tenant,
            user_id=user_id,
            defaults={"role": "owner", "is_active": True},
        )

    Klient.objects.filter(tenant__isnull=True).update(tenant=tenant)
    AccessToken.objects.filter(connection__isnull=True).update(connection=dotykacka)

    batch, _ = CardBatch.objects.get_or_create(
        tenant=tenant,
        name="Legacy MB-1..600",
        defaults={
            "card_prefix": "MB",
            "start_number": 1,
            "end_number": 600,
            "status": "legacy",
            "design_snapshot": {
                "source": "legacy-import",
                "logo_path": "logo_atelier_cafe.png",
                "background_source": "Marta Banaszek - Obraz II.jpg",
            },
        },
    )

    customers_by_code = {customer.klient_id: customer for customer in Klient.objects.all()}
    invalid_codes = [
        code
        for code in customers_by_code
        if not re.fullmatch(r"MB-([1-9][0-9]{0,2})", code or "")
        or not 1 <= int(code.split("-", 1)[1]) <= 600
    ]
    if invalid_codes:
        raise RuntimeError(
            f"Marta backfill stopped: {len(invalid_codes)} customer card codes are invalid."
        )

    for number in range(1, 601):
        code = f"MB-{number}"
        customer = customers_by_code.get(code)
        card, _ = PhysicalCard.objects.get_or_create(
            code=code,
            defaults={
                "tenant": tenant,
                "batch": batch,
                "number": number,
                "status": "assigned" if customer else "available",
                "customer": customer,
                "is_legacy": True,
                "front_image_path": f"cards/card-{number}/{code}_front.jpg",
                "back_image_path": f"cards/card-{number}/{code}_back.jpg",
                "barcode_image_path": f"cards/card-{number}/barcode.png",
                "cropped_image_path": f"cropped_images/cropped_image_{number}.jpg",
                "apple_pass_path": f"output_passes/pass_{number}.pkpass",
            },
        )
        if customer and card.customer_id is None:
            card.customer = customer
            card.status = "assigned"
            card.save(update_fields=["customer", "status"])


class Migration(migrations.Migration):
    dependencies = [("dotykacka", "0009_tenant_foundation")]
    operations = [
        migrations.RunPython(backfill_marta, reverse_code=migrations.RunPython.noop),
    ]
