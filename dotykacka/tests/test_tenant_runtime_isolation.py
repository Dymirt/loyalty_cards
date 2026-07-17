from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from dotykacka import api_utils
from dotykacka.models import AccessToken

from .base import (
    configure_dotykacka,
    create_klient,
    create_superuser,
    create_tenant,
    default_tenant,
)


class TenantRuntimeIsolationTests(TestCase):
    def test_cached_dotykacka_token_is_scoped_to_connection(self):
        marta = default_tenant()
        second = create_tenant()
        marta_connection = configure_dotykacka(marta)
        second_connection = configure_dotykacka(second)
        AccessToken.objects.create(connection=marta_connection, token="marta-token")
        AccessToken.objects.create(connection=second_connection, token="second-token")

        with patch("dotykacka.api_utils.get_access_token") as get_access_token:
            self.assertEqual(
                api_utils.get_valid_access_token(marta_connection),
                "marta-token",
            )
            self.assertEqual(
                api_utils.get_valid_access_token(second_connection),
                "second-token",
            )
        get_access_token.assert_not_called()

    @patch("dotykacka.views.send_contact_to_brevo", return_value=True)
    def test_legacy_bulk_action_operates_only_on_default_tenant(self, send_to_brevo):
        marta_customer = create_klient("MB-12")
        second = create_tenant()
        create_klient("SC-12", tenant=second)
        operator = create_superuser()
        self.client.force_login(operator)

        response = self.client.post(reverse("dotykacka:add_all_to_brevo"))

        self.assertEqual(response.status_code, 302)
        send_to_brevo.assert_called_once_with(marta_customer)

