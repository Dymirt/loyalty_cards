import json
import zipfile
from concurrent.futures import ThreadPoolExecutor
from tempfile import TemporaryDirectory

from django.core.exceptions import ValidationError
from django.db import close_old_connections
from django.test import (
    TestCase,
    TransactionTestCase,
    override_settings,
    skipUnlessDBFeature,
)
from django.utils import timezone

from billing.models import PrintQuoteConsumption, UsageEvent
from billing.services import create_print_quote, accept_quote
from cards.models import CardBatch, PhysicalCard
from dotykacka.models import AuditEvent
from dotykacka.tests.base import create_superuser, create_tenant

from printing.models import (
    FulfillmentEvent,
    PrintJob,
    PrintPackage,
    PrintRequest,
    PrintRun,
    PrintRunCard,
)
from printing.services import (
    allocate_print_run,
    approve_print_request,
    cancel_print_request,
    claim_next_print_job,
    complete_print_job,
    confirm_legacy_reconciliation,
    correct_fulfillment,
    fail_print_job,
    generate_print_package,
    legacy_reconciliation_preview,
    record_fulfillment,
    submit_print_request,
)

from .factories import (
    create_accepted_quote,
    create_request_inputs,
    delivery_values,
)


class PrintingServiceTests(TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.override = override_settings(
            MEDIA_ROOT=self.directory.name,
            PRINT_PACKAGE_ROOT=self.directory.name + "/print-packages",
        )
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.addCleanup(self.directory.cleanup)
        self.tenant = create_tenant(slug="print-cafe", card_prefix="PC")
        self.owner, self.design, self.price, self.quote = create_request_inputs(
            self.tenant,
            quantity=2,
        )
        self.operator = create_superuser("print-operator")

    def submit(self, *, quote=None, key="request-1"):
        return submit_print_request(
            tenant=self.tenant,
            design=self.design,
            quote=quote or self.quote,
            requested_by=self.owner,
            idempotency_key=key,
            proof_approved=True,
            **delivery_values(),
        )[0]

    def allocate(self, request=None):
        request = request or self.submit()
        approve_print_request(print_request=request, actor=self.operator)
        return allocate_print_run(print_request=request, actor=self.operator)[0]

    def generate(self, run=None):
        run = run or self.allocate()
        job = claim_next_print_job(worker_id="test-worker")
        package = generate_print_package(job=job)
        complete_print_job(job)
        return run, package

    def test_submission_is_idempotent_and_freezes_proof_quote_and_delivery(self):
        first, created = submit_print_request(
            tenant=self.tenant,
            design=self.design,
            quote=self.quote,
            requested_by=self.owner,
            idempotency_key="same-request",
            proof_approved=True,
            **delivery_values(),
        )
        retry, retry_created = submit_print_request(
            tenant=self.tenant,
            design=self.design,
            quote=self.quote,
            requested_by=self.owner,
            idempotency_key="same-request",
            proof_approved=True,
            **delivery_values(),
        )

        self.assertTrue(created)
        self.assertFalse(retry_created)
        self.assertEqual(first.pk, retry.pk)
        self.assertEqual(first.snapshot["quote"]["total_amount"], "20.00")
        self.assertEqual(first.snapshot["proof"]["combined_sha256"], first.proof_checksum)
        self.assertEqual(first.status_events.count(), 1)
        first.delivery_city = "Changed"
        with self.assertRaises(ValidationError):
            first.save()

    def test_allocation_never_overlaps_and_consumes_quote_once(self):
        first = self.submit()
        first_run = self.allocate(first)
        second_quote = create_accepted_quote(
            self.tenant,
            self.price,
            quantity=2,
            key="quote-2",
            actor=self.owner,
        )
        second = self.submit(quote=second_quote, key="request-2")
        second_run = self.allocate(second)

        self.assertEqual((first_run.start_number, first_run.end_number), (1, 2))
        self.assertEqual((second_run.start_number, second_run.end_number), (3, 4))
        self.assertEqual(PrintRunCard.objects.count(), 4)
        self.assertEqual(
            PhysicalCard.objects.filter(tenant=self.tenant)
            .values("code")
            .distinct()
            .count(),
            4,
        )
        self.assertEqual(PrintQuoteConsumption.objects.count(), 2)
        self.assertEqual(
            UsageEvent.objects.filter(kind=UsageEvent.Kind.PHYSICAL_CARD_PRODUCED).count(),
            2,
        )
        same_run, created = allocate_print_run(
            print_request=first,
            actor=self.operator,
        )
        self.assertFalse(created)
        self.assertEqual(same_run.pk, first_run.pk)
        self.assertEqual(PrintQuoteConsumption.objects.count(), 2)

    def test_worker_builds_valid_immutable_traceable_package(self):
        run, package = self.generate()
        run.refresh_from_db()
        request = run.print_request
        request.refresh_from_db()

        self.assertEqual(run.status, PrintRun.Status.READY)
        self.assertEqual(request.status, PrintRequest.Status.READY)
        self.assertEqual(run.batch.status, CardBatch.Status.GENERATED)
        self.assertEqual(package.manifest["file_count"], 8)
        self.assertEqual(len(package.manifest["cards"]), 2)
        for run_card in run.run_cards.all():
            self.assertIsNotNone(run_card.crop_plan_id)
            self.assertIsNotNone(run_card.front_artifact_id)
            self.assertIsNotNone(run_card.back_artifact_id)
            self.assertIsNotNone(run_card.barcode_artifact_id)
        package_path = self.directory.name + "/print-packages/" + package.storage_path
        with zipfile.ZipFile(package_path) as archive:
            names = archive.namelist()
            self.assertIn("manifest.json", names)
            self.assertIn("job-summary.txt", names)
            manifest = json.loads(archive.read("manifest.json"))
            self.assertEqual(manifest["print_run"]["id"], run.pk)
            self.assertEqual(len([name for name in names if name.endswith("front.jpg")]), 2)
            self.assertEqual(len([name for name in names if name.endswith("back.jpg")]), 2)
        package.sha256 = "0" * 64
        with self.assertRaises(ValidationError):
            package.save()
        with self.assertRaises(ValidationError):
            package.delete()

    def test_fulfillment_is_controlled_and_corrections_are_compensating_events(self):
        run, _package = self.generate()
        request = run.print_request
        for index, event_type in enumerate(
            (
                FulfillmentEvent.Kind.PRINTING,
                FulfillmentEvent.Kind.PRINTED,
                FulfillmentEvent.Kind.PACKED,
                FulfillmentEvent.Kind.DISPATCHED,
                FulfillmentEvent.Kind.DELIVERED,
            ),
            1,
        ):
            event, created = record_fulfillment(
                print_request=request,
                event_type=event_type,
                actor=self.operator,
                idempotency_key=f"fulfillment-{index}",
                reference="TRACK-1",
            )
            self.assertTrue(created)
            request.refresh_from_db()
        self.assertEqual(request.status, PrintRequest.Status.DELIVERED)
        original = FulfillmentEvent.objects.get(event_type=FulfillmentEvent.Kind.DELIVERED)
        correction, created = correct_fulfillment(
            event=original,
            actor=self.operator,
            idempotency_key="correction-1",
            reason="Wrong delivery reference",
            reference="TRACK-2",
        )
        self.assertTrue(created)
        self.assertEqual(correction.compensates, original)
        self.assertEqual(original.reference, "TRACK-1")
        self.assertEqual(FulfillmentEvent.objects.count(), 6)
        original.notes = "rewrite"
        with self.assertRaises(ValidationError):
            original.save()

    def test_cancelled_allocated_codes_are_void_and_never_reused(self):
        request = self.submit()
        run = self.allocate(request)
        cancel_print_request(
            print_request=request,
            actor=self.operator,
            reason="Tenant cancelled before generation",
        )
        request.refresh_from_db()
        run.refresh_from_db()
        self.assertEqual(request.status, PrintRequest.Status.CANCELLED)
        self.assertEqual(run.status, PrintRun.Status.CANCELLED)
        self.assertEqual(
            PhysicalCard.objects.filter(batch=run.batch, status=PhysicalCard.Status.VOID).count(),
            2,
        )
        self.assertEqual(PrintJob.objects.get(print_run=run).status, PrintJob.Status.CANCELLED)

    def test_terminal_worker_failure_preserves_trace_and_marks_request_failed(self):
        run = self.allocate()
        job = claim_next_print_job(worker_id="failing-worker")
        PrintJob.objects.filter(pk=job.pk).update(attempts=job.max_attempts)
        job.refresh_from_db()

        fail_print_job(job, RuntimeError("synthetic production failure"))

        job.refresh_from_db()
        run.refresh_from_db()
        request = run.print_request
        request.refresh_from_db()
        self.assertEqual(job.status, PrintJob.Status.FAILED)
        self.assertEqual(run.status, PrintRun.Status.FAILED)
        self.assertEqual(request.status, PrintRequest.Status.FAILED)
        self.assertEqual(PrintRunCard.objects.filter(print_run=run).count(), run.quantity)

    def test_legacy_reconciliation_changes_only_append_only_events_and_audit(self):
        legacy_batch = CardBatch.objects.create(
            tenant=self.tenant,
            design=self.design,
            name="Legacy range",
            card_prefix=self.tenant.card_prefix,
            start_number=50,
            end_number=51,
            status=CardBatch.Status.LEGACY,
        )
        cards = [
            PhysicalCard.objects.create(
                tenant=self.tenant,
                batch=legacy_batch,
                code=f"{self.tenant.card_prefix}-{number}",
                number=number,
                status=PhysicalCard.Status.AVAILABLE,
                is_legacy=True,
                front_image_path=f"legacy/{number}/front.jpg",
            )
            for number in (50, 51)
        ]
        before = list(
            PhysicalCard.objects.filter(pk__in=[card.pk for card in cards]).values(
                "pk", "status", "front_image_path", "customer_id"
            )
        )
        preview = legacy_reconciliation_preview(
            tenant=self.tenant,
            batch=legacy_batch,
            start_number=50,
            end_number=51,
        )
        created = confirm_legacy_reconciliation(
            tenant=self.tenant,
            batch=legacy_batch,
            start_number=50,
            end_number=51,
            expected_count=preview["count"],
            event_types=(FulfillmentEvent.Kind.PRINTED, FulfillmentEvent.Kind.DELIVERED),
            actor=self.operator,
            occurred_at=timezone.now(),
            reference="LEGACY-DELIVERY",
            notes="Verified paper record",
        )
        retry = confirm_legacy_reconciliation(
            tenant=self.tenant,
            batch=legacy_batch,
            start_number=50,
            end_number=51,
            expected_count=2,
            event_types=(FulfillmentEvent.Kind.PRINTED, FulfillmentEvent.Kind.DELIVERED),
            actor=self.operator,
            occurred_at=timezone.now(),
            reference="LEGACY-DELIVERY",
            notes="Verified paper record",
        )

        self.assertEqual(len(created), 4)
        self.assertEqual(retry, [])
        self.assertEqual(FulfillmentEvent.objects.filter(physical_card__in=cards).count(), 4)
        self.assertEqual(
            list(
                PhysicalCard.objects.filter(pk__in=[card.pk for card in cards]).values(
                    "pk", "status", "front_image_path", "customer_id"
                )
            ),
            before,
        )
        self.assertEqual(UsageEvent.objects.count(), 0)
        self.assertTrue(AuditEvent.objects.filter(action="printing.legacy_reconciled").exists())


class ConcurrentAllocationTests(TransactionTestCase):
    reset_sequences = True

    @skipUnlessDBFeature("has_select_for_update")
    def test_concurrent_tenant_allocations_do_not_overlap(self):
        with TemporaryDirectory() as directory, override_settings(MEDIA_ROOT=directory):
            tenant = create_tenant(slug="parallel-print", card_prefix="PP")
            owner, design, price, first_quote = create_request_inputs(tenant, quantity=2)
            operator = create_superuser("parallel-operator")
            second_quote = create_accepted_quote(
                tenant,
                price,
                quantity=2,
                key="parallel-quote-2",
                actor=owner,
            )
            requests = []
            for key, quote in (("parallel-1", first_quote), ("parallel-2", second_quote)):
                item, _ = submit_print_request(
                    tenant=tenant,
                    design=design,
                    quote=quote,
                    requested_by=owner,
                    idempotency_key=key,
                    proof_approved=True,
                    **delivery_values(),
                )
                approve_print_request(print_request=item, actor=operator)
                requests.append(item.pk)

            def allocate(request_pk):
                close_old_connections()
                request = PrintRequest.objects.get(pk=request_pk)
                local_operator = type(operator).objects.get(pk=operator.pk)
                run, _ = allocate_print_run(
                    print_request=request,
                    actor=local_operator,
                )
                result = (run.start_number, run.end_number)
                close_old_connections()
                return result

            with ThreadPoolExecutor(max_workers=2) as pool:
                ranges = sorted(pool.map(allocate, requests))

            self.assertEqual(ranges, [(1, 2), (3, 4)])
            self.assertEqual(
                PhysicalCard.objects.filter(tenant=tenant)
                .values("code")
                .distinct()
                .count(),
                4,
            )
