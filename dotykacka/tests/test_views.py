from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .base import configure_dotykacka, create_klient, create_superuser


class AdministrativeViewTests(TestCase):
    def setUp(self):
        self.superuser = create_superuser()

    def test_customer_list_requires_superuser(self):
        response = self.client.get(reverse("dotykacka:customers"))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith("/admin/login/"))

    def test_customer_list_renders_valid_card_preview(self):
        self.client.force_login(self.superuser)
        create_klient("MB-12")
        response = self.client.get(reverse("dotykacka:customers"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "cropped_image_12.jpg")
        self.assertContains(response, "/media/output_passes/pass_12.pkpass")

    def test_customer_list_does_not_require_provider_availability(self):
        self.client.force_login(self.superuser)
        response = self.client.get(reverse("dotykacka:customers"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Nie udało się pobrać")

    def test_mutating_admin_routes_reject_get(self):
        self.client.force_login(self.superuser)
        urls = (
            reverse("dotykacka:send_pass", args=["MB-12"]),
            reverse("dotykacka:add_all_to_brevo"),
            reverse("dotykacka:generate_jwt_passes"),
            reverse("dotykacka:send_passes_to_all"),
        )
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 405)

    def test_mutating_admin_routes_reject_regular_user(self):
        regular_user = get_user_model().objects.create_user(
            username="regular-user",
            password="test-only-password",
        )
        self.client.force_login(regular_user)
        urls = (
            reverse("dotykacka:send_pass", args=["MB-12"]),
            reverse("dotykacka:add_all_to_brevo"),
            reverse("dotykacka:generate_jwt_passes"),
            reverse("dotykacka:send_passes_to_all"),
        )
        for url in urls:
            with self.subTest(url=url):
                response = self.client.post(url)
                self.assertEqual(response.status_code, 302)
                self.assertTrue(response.url.startswith("/admin/login/"))

    @patch("dotykacka.views.send_pass_email")
    def test_send_one_pass_is_synchronous_and_authorized(self, send_email):
        klient = create_klient("MB-12")
        self.client.force_login(self.superuser)
        response = self.client.post(reverse("dotykacka:send_pass", args=["mb-12"]))
        self.assertRedirects(
            response,
            reverse("dotykacka:customers"),
            fetch_redirect_response=False,
        )
        send_email.assert_called_once_with(klient)

    @patch("dotykacka.views.send_contact_to_brevo", return_value=True)
    def test_brevo_bulk_action_is_scoped_to_post(self, send_to_brevo):
        create_klient("MB-12")
        self.client.force_login(self.superuser)
        response = self.client.post(reverse("dotykacka:add_all_to_brevo"))
        self.assertRedirects(
            response,
            reverse("dotykacka:customers"),
            fetch_redirect_response=False,
        )
        send_to_brevo.assert_called_once()

    @patch("dotykacka.views.send_pass_email")
    @patch("dotykacka.views.generate_google_wallet_for_klient")
    def test_google_bulk_generation_never_sends_email(self, generate_google, send_email):
        create_klient("MB-12")
        create_klient("MB-13")
        self.client.force_login(self.superuser)
        response = self.client.post(reverse("dotykacka:generate_jwt_passes"))
        self.assertRedirects(
            response,
            reverse("dotykacka:customers"),
            fetch_redirect_response=False,
        )
        self.assertEqual(generate_google.call_count, 2)
        send_email.assert_not_called()

    @patch("dotykacka.views.send_pass_email")
    def test_bulk_email_uses_service_without_csv_log(self, send_email):
        create_klient("MB-12")
        self.client.force_login(self.superuser)
        response = self.client.post(reverse("dotykacka:send_passes_to_all"))
        self.assertRedirects(
            response,
            reverse("dotykacka:customers"),
            fetch_redirect_response=False,
        )
        send_email.assert_called_once()

    @patch("dotykacka.views.dotykacka_api.get_valid_access_token", return_value="secret")
    def test_access_token_diagnostic_never_renders_token(self, get_token):
        connection = configure_dotykacka()
        self.client.force_login(self.superuser)
        response = self.client.get(reverse("dotykacka:acces_token"))
        self.assertContains(response, "dostępny", html=False)
        self.assertNotContains(response, "secret")
        get_token.assert_called_once_with(connection)
