from django.contrib.auth import get_user_model

from dotykacka.models import (
    AccessToken,
    CardBatch,
    IntegrationConnection,
    Klient,
    PhysicalCard,
    Tenant,
    TenantBrand,
    TenantMembership,
)
from dotykacka.tenancy import get_default_tenant


REGISTRATION_DATA = {
    "first_name": "Jan",
    "last_name": "Kowalski",
    "email": "jan@example.test",
    "phone": "501234567",
    "barcode": "MB-12",
    "marketing_consent": "1",
}


def default_tenant():
    return get_default_tenant()


def create_tenant(
    *,
    name="Second Café",
    slug="second-cafe",
    card_prefix="SC",
):
    tenant = Tenant.objects.create(
        name=name,
        slug=slug,
        card_prefix=card_prefix,
    )
    TenantBrand.objects.create(
        tenant=tenant,
        public_name=name,
        marketing_consent_text=f"Marketing consent for {name}",
    )
    return tenant


def create_physical_card(tenant=None, *, number=12, status=PhysicalCard.Status.AVAILABLE):
    tenant = tenant or default_tenant()
    code = f"{tenant.card_prefix}-{number}"
    card = PhysicalCard.objects.filter(tenant=tenant, code=code).first()
    if card:
        return card
    batch, _ = CardBatch.objects.get_or_create(
        tenant=tenant,
        name="Test cards",
        defaults={
            "card_prefix": tenant.card_prefix,
            "start_number": number,
            "end_number": number,
        },
    )
    return PhysicalCard.objects.create(
        tenant=tenant,
        batch=batch,
        code=code,
        number=number,
        status=status,
    )


def create_klient(card_code="MB-12", tenant=None, **overrides):
    tenant = tenant or default_tenant()
    values = {
        "tenant": tenant,
        "klient_id": card_code,
        "email": "customer@example.test",
        "phone": "501234567",
        "first_name": "Test",
        "last_name": "Customer",
        "google_jwt_url": "https://wallet.example.test/save",
    }
    values.update(overrides)
    return Klient.objects.create(**values)


def configure_integration(tenant=None, provider=None, *, configuration=None, secrets=None):
    tenant = tenant or default_tenant()
    connection, _ = IntegrationConnection.objects.get_or_create(
        tenant=tenant,
        provider=provider,
    )
    connection.enabled = True
    connection.configuration = configuration or {}
    connection.set_credentials(secrets or {})
    connection.save()
    return connection


def configure_dotykacka(tenant=None):
    return configure_integration(
        tenant,
        IntegrationConnection.Provider.DOTYKACKA,
        configuration={"cloud_id": 123, "discount_group_id": 456},
        secrets={
            "authorization_token": "authorization-token",
            "refresh_token": "authorization-token",
        },
    )


def configure_brevo(tenant=None):
    return configure_integration(
        tenant,
        IntegrationConnection.Provider.BREVO,
        configuration={"list_id": 25, "default_phone_country_code": "+48"},
        secrets={"api_key": "brevo-test-key"},
    )


def configure_google_wallet(tenant=None):
    return configure_integration(
        tenant,
        IntegrationConnection.Provider.GOOGLE_WALLET,
        configuration={"issuer_id": "issuer123", "class_suffix": "MB"},
    )


def create_access_token(token="test-token", tenant=None):
    connection = configure_dotykacka(tenant)
    return AccessToken.objects.create(connection=connection, token=token)


def create_superuser(username="operator"):
    return get_user_model().objects.create_superuser(
        username=username,
        email=f"{username}@example.test",
        password="test-only-password",
    )


def create_tenant_owner(tenant, username="tenant-owner"):
    user = get_user_model().objects.create_user(
        username=username,
        email=f"{username}@example.test",
        password="test-only-password",
    )
    TenantMembership.objects.create(
        tenant=tenant,
        user=user,
        role=TenantMembership.Role.OWNER,
    )
    return user
