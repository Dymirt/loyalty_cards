from tempfile import TemporaryDirectory

from django.test import TestCase, override_settings

from card_artwork.models import CropPlan
from card_artwork.services import (
    build_sample_sheet,
    generate_card_artifacts,
    render_card,
    spec_from_design,
)
from dotykacka.tests.base import create_physical_card, create_tenant
from dotykacka.tests.test_card_designs import create_design


class CropPlanTests(TestCase):
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
