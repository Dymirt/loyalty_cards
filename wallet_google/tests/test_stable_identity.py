from unittest.mock import patch

from django.test import TestCase, override_settings

from wallet_google.services import issuer
from wallets.models import WalletPass

from dotykacka.tests.base import configure_google_wallet, create_klient


@override_settings(GOOGLE_WALLET_ISSUER_ID="3388000000022973962")
class GoogleWalletStableIdentityTests(TestCase):
    @patch("wallet_google.services.get_wallet_url", side_effect=["https://save/one", "https://save/two"])
    def test_retry_reuses_one_object_identity(self, get_wallet_url):
        customer = create_klient("MB-12", google_jwt_url="")
        configure_google_wallet(customer.tenant)
        issuer.issue(customer, remote_sync=False)
        first_id = WalletPass.objects.get(customer=customer).google_object_id
        issuer.issue(customer, remote_sync=False)
        wallet = WalletPass.objects.get(customer=customer)
        self.assertEqual(wallet.google_object_id, first_id)
        self.assertEqual(WalletPass.objects.filter(customer=customer).count(), 1)
        self.assertEqual(
            [call.kwargs["object_id"] for call in get_wallet_url.call_args_list],
            [first_id, first_id],
        )
        self.assertEqual(
            [call.kwargs["class_suffix"] for call in get_wallet_url.call_args_list],
            [customer.tenant.card_prefix, customer.tenant.card_prefix],
        )
