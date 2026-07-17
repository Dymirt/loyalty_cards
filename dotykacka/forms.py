"""Deprecated form imports preserved for historical callers."""

from brevo.forms import BrevoIntegrationForm
from card_artwork.forms import CardDesignForm
from enrollment.forms import LoyaltyCustomerRegistrationForm, registration_form_data
from pos_dotykacka.forms import DotykackaIntegrationForm
from tenants.forms import TenantBrandForm
from wallet_google.forms import GoogleWalletIntegrationForm

__all__ = [
    "BrevoIntegrationForm",
    "CardDesignForm",
    "DotykackaIntegrationForm",
    "GoogleWalletIntegrationForm",
    "LoyaltyCustomerRegistrationForm",
    "TenantBrandForm",
    "registration_form_data",
]
