from django.test import TestCase
from django.urls import reverse

from dotykacka.tests.base import create_tenant, create_tenant_owner
from tenants.authorization import can_access_tenant


class TenantDomainTests(TestCase):
    def test_owner_access_and_canonical_route_are_tenant_scoped(self):
        tenant = create_tenant()
        owner = create_tenant_owner(tenant)
        other = create_tenant(name="Other", slug="other", card_prefix="OT")

        self.assertTrue(can_access_tenant(owner, tenant))
        self.assertFalse(can_access_tenant(owner, other))
        self.client.force_login(owner)
        response = self.client.get(reverse("tenants:portal", args=[tenant.slug]))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "tenants/portal.html")
