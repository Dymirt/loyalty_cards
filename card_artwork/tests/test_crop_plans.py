from tempfile import TemporaryDirectory

from django.test import TestCase, override_settings

from card_artwork.models import CropPlan
from card_artwork.services import (
    build_sample_sheet,
    calculate_capacity_for_dimensions,
    calculate_crop_plan,
    calculate_deterministic_crop_position,
    generate_card_artifacts,
    get_or_create_crop_plan,
    render_card,
    spec_from_design,
)
from dotykacka.tests.base import create_physical_card, create_tenant
from dotykacka.tests.test_card_designs import create_design


class CropPlanTests(TestCase):
    def test_native_master_capacity_and_first_ten_thousand_positions_are_unique(self):
        capacity = calculate_capacity_for_dimensions(
            source_width=5193,
            source_height=6999,
            card_width=1011,
            card_height=638,
            requested_count=10_000,
        )

        self.assertEqual(capacity.resized_width, 5193)
        self.assertEqual(capacity.resized_height, 6999)
        self.assertEqual(capacity.visually_distinct_capacity, 680)
        self.assertGreater(capacity.exact_unique_capacity, 26_000_000)
        self.assertTrue(capacity.visual_capacity_reached)
        self.assertFalse(capacity.exact_capacity_reached)

        positions = {
            calculate_deterministic_crop_position(
                checksum="1" * 64,
                capacity=capacity,
                card_code=f"MB-{number}",
            )
            for number in range(1, 10_001)
        }

        self.assertEqual(len(positions), 10_000)
        self.assertGreater(max(left for left, _ in positions), 4000)
        self.assertGreater(max(top for _, top in positions), 6000)

    def test_identical_inputs_reproduce_crop_bytes_and_metadata(self):
        with TemporaryDirectory() as directory, override_settings(MEDIA_ROOT=directory):
            tenant = create_tenant()
            design = create_design(tenant)
            spec = spec_from_design(design)

            first = render_card(spec, "SC-12")
            second = render_card(spec, "SC-12")

            self.assertEqual(first.front, second.front)
            self.assertEqual(first.crop_plan.metadata(), second.crop_plan.metadata())
            self.assertEqual(build_sample_sheet(spec, count=3), build_sample_sheet(spec, count=3))

    def test_cli_web_shared_service_persists_exact_plan_once(self):
        with TemporaryDirectory() as directory, override_settings(MEDIA_ROOT=directory):
            tenant = create_tenant()
            design = create_design(tenant)
            card = create_physical_card(tenant, number=12)

            first = generate_card_artifacts(design=design, physical_card=card)
            second = generate_card_artifacts(design=design, physical_card=card)
            plan = CropPlan.objects.get(design=design, card_code=card.code)

            self.assertEqual(plan.physical_card, card)
            self.assertEqual(first[0].metadata["crop_plan_id"], plan.pk)
            self.assertEqual(second[0].metadata["crop_plan_id"], plan.pk)
            self.assertNotEqual(first[0].storage_path, second[0].storage_path)

    def test_existing_v1_plan_is_reused_without_recalculation_or_rewrite(self):
        with TemporaryDirectory() as directory, override_settings(MEDIA_ROOT=directory):
            tenant = create_tenant()
            design = create_design(tenant)
            card = create_physical_card(tenant, number=12)
            plan_data = calculate_crop_plan(spec_from_design(design), card.code)
            legacy_values = plan_data.metadata()
            legacy_values["render_version"] = "card-artwork-v1"
            legacy = CropPlan.objects.create(
                tenant=tenant,
                design=design,
                physical_card=card,
                **legacy_values,
            )

            stored, restored = get_or_create_crop_plan(
                design=design,
                card_code=card.code,
                physical_card=card,
            )

            self.assertEqual(stored.pk, legacy.pk)
            self.assertEqual(restored.render_version, "card-artwork-v1")
            self.assertEqual(CropPlan.objects.filter(design=design).count(), 1)
