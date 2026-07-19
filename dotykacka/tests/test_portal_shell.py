import json
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from dotykacka.models import TenantMembership

from .base import (
    create_superuser,
    create_tenant,
    create_tenant_owner,
    default_tenant,
)


class PortalStaticAssetTests(SimpleTestCase):
    def test_pinned_local_assets_and_compiled_tailwind_are_present(self):
        base_dir = Path(settings.BASE_DIR)
        css = base_dir / "static/css/portal.v1.css"
        htmx = base_dir / "static/vendor/htmx-2.0.10.min.js"
        scanner = base_dir / "static/vendor/zxing-library-0.21.3.min.js"
        package = json.loads((base_dir / "package.json").read_text(encoding="utf-8"))

        self.assertTrue(css.is_file())
        self.assertTrue(htmx.is_file())
        self.assertTrue(scanner.is_file())
        self.assertIn(".portal-card", css.read_text(encoding="utf-8"))
        self.assertEqual(package["dependencies"]["htmx.org"], "2.0.10")
        self.assertEqual(package["dependencies"]["@zxing/library"], "0.21.3")
        self.assertEqual(package["devDependencies"]["tailwindcss"], "4.3.2")


class PortalShellViewTests(TestCase):
    def setUp(self):
        self.tenant = default_tenant()

    def test_public_pages_use_local_shell_without_legacy_ui_cdns(self):
        for url in (
            reverse("index"),
            reverse("dotykacka:tenant_register", args=[self.tenant.slug]),
        ):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "/static/css/portal.v1.css")
                self.assertContains(response, "/static/vendor/htmx-2.0.10.min.js")
                self.assertNotContains(response, "bootstrap")
                self.assertNotContains(response, "jquery")
                self.assertNotContains(response, "unpkg.com")
                self.assertNotContains(response, "@latest")

        registration = self.client.get(
            reverse("dotykacka:tenant_register", args=[self.tenant.slug])
        )
        self.assertContains(
            registration,
            "/static/vendor/zxing-library-0.21.3.min.js",
        )
        self.assertContains(registration, "/static/js/card-scanner.v1.js")
        self.assertContains(registration, 'method="post"')

    def test_login_uses_portal_shell(self):
        response = self.client.get(reverse("login"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Portal SaaS")
        self.assertContains(response, "/static/css/portal.v1.css")

    def test_tenant_portal_requires_membership(self):
        url = reverse("dotykacka:tenant_portal", args=[self.tenant.slug])
        anonymous = self.client.get(url)
        self.assertRedirects(
            anonymous,
            f"{reverse('login')}?next={url}",
            fetch_redirect_response=False,
        )

        other = create_tenant()
        self.client.force_login(create_tenant_owner(other))
        self.assertEqual(self.client.get(url).status_code, 403)

    def test_owner_and_staff_can_view_tenant_dashboard(self):
        url = reverse("dotykacka:tenant_portal", args=[self.tenant.slug])
        owner = create_tenant_owner(self.tenant)
        self.client.force_login(owner)
        owner_response = self.client.get(url)
        self.assertEqual(owner_response.status_code, 200)
        self.assertContains(owner_response, "Karty dostępne")
        self.assertContains(owner_response, "Integracje")

        staff = get_user_model().objects.create_user(
            username="portal-staff",
            password="test-only-password",
        )
        TenantMembership.objects.create(
            tenant=self.tenant,
            user=staff,
            role=TenantMembership.Role.STAFF,
        )
        self.client.force_login(staff)
        staff_response = self.client.get(url)
        self.assertEqual(staff_response.status_code, 200)
        self.assertNotContains(staff_response, "Konfiguruj")

    def test_integration_forms_are_htmx_enhanced_with_plain_post_fallback(self):
        owner = create_tenant_owner(self.tenant)
        self.client.force_login(owner)
        response = self.client.get(
            reverse("dotykacka:integration_settings", args=[self.tenant.slug])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'hx-post="', count=4)
        self.assertContains(response, 'hx-select="#integration-settings-content"', count=3)
        self.assertContains(response, 'method="post"', count=6)
        self.assertContains(
            response,
            reverse("pos_dotykacka:connect", args=[self.tenant.slug]),
        )
        self.assertContains(response, "autoryzujesz bezpośrednio u dostawcy")
        self.assertNotContains(
            response,
            reverse(
                "integrations:test",
                args=[self.tenant.slug, "google_wallet"],
            ),
        )
        self.assertNotContains(response, "authorization-token")

    def test_print_center_is_platform_only_and_separate_from_client_navigation(self):
        url = reverse("dotykacka:platform_print_center")
        regular = get_user_model().objects.create_user(
            username="regular-platform-user",
            password="test-only-password",
        )
        self.client.force_login(regular)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith("/admin/login/"))

        self.client.force_login(create_superuser())
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Centrum druku")
        self.assertContains(response, self.tenant.name)
        self.assertContains(response, "Kolejka zamówień")
        self.assertContains(response, "Historyczne karty — tylko podgląd")
