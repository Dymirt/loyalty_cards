"""Customer persistence and consent-evidence services."""

import hashlib
import re

from .models import ConsentRecord, Customer


def list_legacy_provider_customers(tenant):
    """Compatibility-shaped projection from the tenant-owned local source."""

    customers = [
        {
            "firstName": customer.first_name,
            "lastName": customer.last_name,
            "barcode": customer.klient_id,
        }
        for customer in Customer.objects.filter(tenant=tenant).order_by("klient_id")
    ]
    for customer in customers:
        match = re.fullmatch(r"[A-Z0-9]+-([1-9][0-9]*)", customer.get("barcode") or "")
        customer["barcode_decode"] = match.group(1) if match else ""
    return customers


def create_customer(*, tenant, card_code, first_name, last_name, email, phone):
    return Customer.objects.create(
        tenant=tenant,
        klient_id=card_code,
        email=email,
        phone=phone,
        first_name=first_name,
        last_name=last_name,
        google_jwt_url="",
    )


def record_marketing_consent(*, customer, consent_text, source="registration"):
    checksum = hashlib.sha256(consent_text.encode("utf-8")).hexdigest()
    record = ConsentRecord(
        tenant=customer.tenant,
        customer=customer,
        purpose="marketing",
        policy_version=f"sha256:{checksum[:16]}",
        consent_text=consent_text,
        consent_text_sha256=checksum,
        granted=True,
        source=source,
    )
    record.full_clean()
    record.save()
    return record
