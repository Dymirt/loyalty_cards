"""Small enrollment orchestrator over owning-domain services."""

from django.db import transaction

from billing.services import record_card_issuance
from cards.services import assign_locked_card, lock_available_card
from customers.services import create_customer, record_marketing_consent



@transaction.atomic
def register_customer_with_card(*, tenant, cleaned_data):
    card = lock_available_card(tenant=tenant, code=cleaned_data["barcode"])
    customer = create_customer(
        tenant=tenant,
        card_code=cleaned_data["barcode"],
        first_name=cleaned_data["first_name"],
        last_name=cleaned_data["last_name"],
        email=cleaned_data["email"],
        phone=cleaned_data["phone"],
    )
    assign_locked_card(card=card, customer=customer)
    record_card_issuance(
        tenant=tenant,
        card_identity=card.pk,
        physical=True,
        metadata={"source": "public_registration"},
    )
    consent_text = getattr(tenant.brand, "marketing_consent_text", "") or "Marketing consent"
    record_marketing_consent(customer=customer, consent_text=consent_text)
    return customer
