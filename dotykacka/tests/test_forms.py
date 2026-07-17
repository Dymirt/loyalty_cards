from django.test import TestCase

from dotykacka.forms import LoyaltyCustomerRegistrationForm, registration_form_data

from .base import REGISTRATION_DATA, create_klient, default_tenant


class RegistrationFormTests(TestCase):
    def test_valid_form_normalizes_card_code(self):
        form = LoyaltyCustomerRegistrationForm(
            {**REGISTRATION_DATA, "barcode": " mb-12 "}, tenant=default_tenant()
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["barcode"], "MB-12")

    def test_rejects_invalid_card_code(self):
        form = LoyaltyCustomerRegistrationForm(
            {**REGISTRATION_DATA, "barcode": "MB-ABC"}, tenant=default_tenant()
        )
        self.assertFalse(form.is_valid())
        self.assertIn("barcode", form.errors)

    def test_rejects_duplicate_card_code(self):
        create_klient("MB-12")
        form = LoyaltyCustomerRegistrationForm(REGISTRATION_DATA, tenant=default_tenant())
        self.assertFalse(form.is_valid())
        self.assertIn("już istnieje", form.errors["barcode"][0])

    def test_requires_valid_phone_and_consent(self):
        data = {**REGISTRATION_DATA, "phone": "+48501234567"}
        data.pop("marketing_consent")
        form = LoyaltyCustomerRegistrationForm(data, tenant=default_tenant())
        self.assertFalse(form.is_valid())
        self.assertIn("phone", form.errors)
        self.assertIn("marketing_consent", form.errors)

    def test_maps_legacy_post_field_names(self):
        legacy_data = {
            "firstName": "Jan",
            "lastName": "Kowalski",
            "email": "jan@example.test",
            "tel": "501234567",
            "barcode": "MB-12",
            "marketing_consent": "1",
        }
        form = LoyaltyCustomerRegistrationForm(
            registration_form_data(legacy_data), tenant=default_tenant()
        )
        self.assertTrue(form.is_valid(), form.errors)
