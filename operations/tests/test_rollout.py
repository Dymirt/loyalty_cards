from copy import deepcopy

from django.test import SimpleTestCase

from operations.management.commands.verify_saas_rollout import (
    _marta_invariant_mismatches,
)


class MartaRolloutInvariantTests(SimpleTestCase):
    def baseline_counts(self):
        return {
            "customers": 267,
            "cards": 600,
            "cards_with_customer": 267,
            "access_tokens": 261,
            "memberships": 1,
            "wallet_identities": 267,
            "integration_providers": ["brevo", "dotykacka", "google_wallet"],
            "dotykacka_refresh_token_configured": True,
            "brevo_api_key_configured": True,
            "cross_tenant_card_customers": 0,
            "cross_tenant_card_batches": 0,
            "cross_tenant_wallet_customers": 0,
            "cross_tenant_wallet_cards": 0,
        }

    def test_historical_baseline_passes(self):
        self.assertEqual(_marta_invariant_mismatches(self.baseline_counts()), {})

    def test_normal_enrollment_and_token_growth_passes(self):
        counts = deepcopy(self.baseline_counts())
        counts.update(
            customers=269,
            cards_with_customer=269,
            wallet_identities=269,
            access_tokens=264,
        )
        self.assertEqual(_marta_invariant_mismatches(counts), {})

    def test_baseline_loss_is_rejected(self):
        counts = deepcopy(self.baseline_counts())
        counts["cards"] = 599
        self.assertEqual(
            _marta_invariant_mismatches(counts)["cards"],
            {"expected_minimum": 600, "actual": 599},
        )

    def test_relational_or_tenant_isolation_mismatch_is_rejected(self):
        counts = deepcopy(self.baseline_counts())
        counts["customers"] = 268
        counts["cross_tenant_wallet_cards"] = 1
        mismatches = _marta_invariant_mismatches(counts)
        self.assertIn("customer_card_ownership", mismatches)
        self.assertIn("customer_wallet_identity", mismatches)
        self.assertIn("cross_tenant_wallet_cards", mismatches)

    def test_missing_provider_or_encrypted_credential_is_rejected(self):
        counts = deepcopy(self.baseline_counts())
        counts["integration_providers"].remove("brevo")
        counts["brevo_api_key_configured"] = False
        mismatches = _marta_invariant_mismatches(counts)
        self.assertEqual(mismatches["integration_providers"]["missing"], ["brevo"])
        self.assertIn("brevo_api_key_configured", mismatches)
