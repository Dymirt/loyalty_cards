from unittest.mock import Mock, patch

import requests
from django.core.exceptions import ImproperlyConfigured
from django.test import TestCase, override_settings
from django.utils import timezone

from dotykacka import api_utils
from dotykacka.models import AccessToken


DOTYKACKA_SETTINGS = {
    "DOTYKACKA_AUTHORIZATION_TOKEN": "authorization-token",
    "DOTYKACKA_CLOUD_ID": 123,
    "DOTYKACKA_DISCOUNT_GROUP_ID": 456,
    "DOTYKACKA_HTTP_TIMEOUT": 7,
}


class DotykackaApiTests(TestCase):
    @override_settings(DOTYKACKA_AUTHORIZATION_TOKEN="", DOTYKACKA_CLOUD_ID=0)
    def test_missing_configuration_fails_before_network(self):
        with self.assertRaises(ImproperlyConfigured):
            api_utils.get_access_token()

    @override_settings(**DOTYKACKA_SETTINGS)
    @patch("dotykacka.api_utils.requests.post")
    def test_new_access_token_is_cached(self, post):
        response = Mock()
        response.json.return_value = {"accessToken": "cached-token"}
        post.return_value = response

        token = api_utils.get_access_token()

        self.assertEqual(token, "cached-token")
        self.assertEqual(AccessToken.objects.get().token, "cached-token")
        post.assert_called_once_with(
            "https://api.dotykacka.cz/v2/signin/token",
            json={"_cloudId": 123},
            headers={
                "Authorization": "authorization-token",
                "Content-Type": "application/json",
            },
            timeout=7,
        )
        response.raise_for_status.assert_called_once_with()

    @override_settings(**DOTYKACKA_SETTINGS)
    @patch("dotykacka.api_utils.requests.post")
    def test_valid_cached_token_avoids_network(self, post):
        AccessToken.objects.create(token="still-valid")
        self.assertEqual(api_utils.get_valid_access_token(), "still-valid")
        post.assert_not_called()

    @override_settings(**DOTYKACKA_SETTINGS)
    @patch("dotykacka.api_utils.get_valid_access_token", return_value="access")
    @patch("dotykacka.api_utils.requests.post")
    def test_register_customer_uses_configured_group(self, post, get_token):
        response = Mock(content=b"{}")
        response.json.return_value = {"ok": True}
        post.return_value = response

        result = api_utils.register_dotykacka_customer(
            "MB-12", "Jan", "Kowalski", "jan@example.test", "501234567"
        )

        self.assertEqual(result, {"ok": True})
        body = post.call_args.kwargs["json"]
        self.assertEqual(body[0]["barcode"], "MB-12")
        self.assertEqual(body[0]["_discountGroupId"], 456)
        self.assertEqual(post.call_args.kwargs["timeout"], 7)
        response.raise_for_status.assert_called_once_with()

    @override_settings(**DOTYKACKA_SETTINGS)
    @patch("dotykacka.api_utils.get_valid_access_token", return_value="access")
    @patch("dotykacka.api_utils.requests.get")
    def test_customer_list_paginates_and_filters_discount_group(self, get, get_token):
        page_one = Mock()
        page_one.json.return_value = {
            "data": [{"barcode": "MB-1", "_discountGroupId": 456}],
            "lastPage": 2,
        }
        page_two = Mock()
        page_two.json.return_value = {
            "data": [
                {"barcode": "MB-2", "_discountGroupId": "456"},
                {"barcode": "OTHER-1", "_discountGroupId": 999},
            ],
            "lastPage": 2,
        }
        get.side_effect = [page_one, page_two]

        customers = api_utils.get_all_customers()

        self.assertEqual([item["barcode"] for item in customers], ["MB-1", "MB-2"])
        self.assertEqual(get.call_count, 2)
        self.assertEqual(get.call_args_list[1].kwargs["params"], {"page": 2})

    @override_settings(**DOTYKACKA_SETTINGS)
    @patch("dotykacka.api_utils.requests.post")
    def test_http_failure_is_propagated(self, post):
        response = Mock()
        response.raise_for_status.side_effect = requests.HTTPError("provider failed")
        post.return_value = response
        with self.assertRaises(requests.HTTPError):
            api_utils.get_access_token()
        self.assertEqual(AccessToken.objects.count(), 0)
