from tempfile import TemporaryDirectory

from django.test import TestCase, override_settings
from django.urls import reverse

from dotykacka.models import AuditEvent
from dotykacka.tests.base import create_superuser, create_tenant, create_tenant_owner
from tenants.models import TenantMembership

from printing.models import PrintRequest
from printing.services import (
    allocate_print_run,
    approve_print_request,
    claim_next_print_job,
    complete_print_job,
    generate_print_package,
    submit_print_request,
)

from .factories import create_request_inputs, delivery_values


class PrintingViewTests(TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.override = override_settings(
            MEDIA_ROOT=self.directory.name,
            PRINT_PACKAGE_ROOT=self.directory.name + "/print-packages",
        )
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.addCleanup(self.directory.cleanup)
        self.tenant = create_tenant(slug="view-print", card_prefix="VP")
        self.owner, self.design, self.price, self.quote = create_request_inputs(
            self.tenant,
            quantity=2,
        )
        self.staff = create_tenant_owner(self.tenant, username="print-staff")
        TenantMembership.objects.filter(user=self.staff).update(
            role=TenantMembership.Role.STAFF
        )
        self.operator = create_superuser("view-operator")

    def test_owner_submits_with_plain_post_and_htmx_redirect(self):
        self.client.force_login(self.owner)
        page = self.client.get(reverse("printing:tenant", args=[self.tenant.slug]))
        self.assertContains(page, "Nowe zamówienie")
        data = {
            "design": self.design.pk,
            "quote": self.quote.pk,
            "proof_approved": "on",
            "idempotency_key": "view-request",
            **delivery_values(),
        }
        response = self.client.post(
            reverse("printing:submit", args=[self.tenant.slug]),
            data,
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 204)
        self.assertEqual(
            response["HX-Redirect"],
            reverse("printing:tenant", args=[self.tenant.slug]),
        )
        self.assertEqual(PrintRequest.objects.filter(tenant=self.tenant).count(), 1)

    def test_staff_and_other_tenant_cannot_manage_requests(self):
        self.client.force_login(self.staff)
        self.assertEqual(
            self.client.get(reverse("printing:tenant", args=[self.tenant.slug])).status_code,
            403,
        )
        other = create_tenant(slug="other-print", card_prefix="OP")
        outsider = create_tenant_owner(other, username="print-outsider")
        self.client.force_login(outsider)
        self.assertEqual(
            self.client.get(reverse("printing:tenant", args=[self.tenant.slug])).status_code,
            403,
        )

    def test_platform_queue_and_actions_are_superuser_only(self):
        request, _ = submit_print_request(
            tenant=self.tenant,
            design=self.design,
            quote=self.quote,
            requested_by=self.owner,
            idempotency_key="platform-request",
            proof_approved=True,
            **delivery_values(),
        )
        self.client.force_login(self.owner)
        self.assertEqual(
            self.client.get(reverse("printing:platform_queue")).status_code,
            302,
        )
        self.assertEqual(
            self.client.post(reverse("printing:approve", args=[request.pk])).status_code,
            302,
        )
        request.refresh_from_db()
        self.assertEqual(request.status, PrintRequest.Status.SUBMITTED)

        self.client.force_login(self.operator)
        page = self.client.get(reverse("printing:platform_queue"))
        self.assertContains(page, "Kolejka zamówień")
        response = self.client.post(
            reverse("printing:approve", args=[request.pk]),
            {"reason": "Proof verified"},
        )
        self.assertRedirects(
            response,
            reverse("printing:platform_detail", args=[request.pk]),
        )
        request.refresh_from_db()
        self.assertEqual(request.status, PrintRequest.Status.APPROVED)

    def test_legacy_preview_is_read_only(self):
        self.client.force_login(self.operator)
        before = PrintRequest.objects.count()
        response = self.client.get(reverse("printing:platform_queue"))
        self.assertContains(response, "Raport bez zmian", count=0)
        self.assertEqual(PrintRequest.objects.count(), before)

    def test_production_package_download_is_superuser_only_and_audited(self):
        request, _ = submit_print_request(
            tenant=self.tenant,
            design=self.design,
            quote=self.quote,
            requested_by=self.owner,
            idempotency_key="download-request",
            proof_approved=True,
            **delivery_values(),
        )
        approve_print_request(print_request=request, actor=self.operator)
        run, _ = allocate_print_run(print_request=request, actor=self.operator)
        job = claim_next_print_job(worker_id="download-worker")
        package = generate_print_package(job=job)
        complete_print_job(job)
        url = reverse("printing:package_download", args=[package.pk])

        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(url).status_code, 302)
        self.client.force_login(self.operator)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/zip")
        self.assertTrue(
            AuditEvent.objects.filter(
                action="printing.package_downloaded",
                object_id=str(package.pk),
            ).exists()
        )
