import json
from dataclasses import replace
from io import BytesIO, StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image, ImageDraw

from dotykacka.models import (
    AuditEvent,
    CardArtifact,
    CardDesign,
    TenantBrandRevision,
)
from dotykacka.services.card_designs import (
    DesignSpec,
    bytes_sha256,
    canonical_checksum,
    generate_card_artifacts,
    render_card,
    spec_from_design,
)

from .base import (
    create_physical_card,
    create_tenant,
    create_tenant_owner,
    default_tenant,
)


def image_bytes(color, *, size=(1400, 900), logo=False):
    stream = BytesIO()
    mode = "RGBA" if logo else "RGB"
    image = Image.new(mode, size, color)
    draw = ImageDraw.Draw(image)
    draw.rectangle((size[0] // 3, 0, size[0] * 2 // 3, size[1]), fill="#D94A64")
    image.save(stream, format="PNG")
    return stream.getvalue()


def upload(name, content):
    return SimpleUploadedFile(name, content, content_type="image/png")


def create_design(tenant, *, version=1, front_text="Second Café"):
    brand_values = {
        "public_name": tenant.name,
        "tagline": front_text,
        "address": "Testowa 1",
        "phone": "+48 500 000 000",
        "email": "brand@example.test",
        "website_url": "https://example.test",
        "email_subject": "Card",
        "email_signature": "Team",
        "marketing_consent_text": "Consent",
    }
    revision = TenantBrandRevision.objects.create(
        tenant=tenant,
        version=version,
        snapshot_checksum=canonical_checksum(brand_values),
        **brand_values,
    )
    design_values = {
        "name": f"Synthetic v{version}",
        "layout_preset": CardDesign.LayoutPreset.CENTERED,
        "crop_mode": CardDesign.CropMode.DETERMINISTIC,
        "focal_x": 50,
        "focal_y": 50,
        "width_px": 1011,
        "height_px": 638,
        "dpi": 300,
        "bleed_mm": "0.0",
        "logo_width_px": 300,
        "front_text": front_text,
        "back_text": "Testowa 1\n+48 500 000 000",
        "foreground_color": "#000000",
        "panel_color": "#FFFFFF",
        "barcode_foreground_color": "#000000",
        "barcode_background_color": "#FFFFFF",
        "font_family": "barlow",
    }
    design = CardDesign(
        tenant=tenant,
        brand_revision=revision,
        version=version,
        design_checksum=canonical_checksum(design_values),
        **design_values,
    )
    design.background_source = upload("background.png", image_bytes("#E9DCC9"))
    design.logo = upload("logo.png", image_bytes("#FFFFFF00", size=(500, 180), logo=True))
    design.full_clean()
    design.save()
    return design


def design_post_data(tenant):
    return {
        "brand-public_name": tenant.name,
        "brand-tagline": "A distinct loyalty brand",
        "brand-address": "Testowa 1",
        "brand-phone": "+48 500 000 000",
        "brand-email": "brand@example.test",
        "brand-website_url": "https://example.test",
        "brand-email_subject": "Your card",
        "brand-email_signature": "Team",
        "brand-marketing_consent_text": "Consent text",
        "design-name": "Launch design",
        "design-layout_preset": CardDesign.LayoutPreset.CENTERED,
        "design-crop_mode": CardDesign.CropMode.DETERMINISTIC,
        "design-focal_x": 50,
        "design-focal_y": 50,
        "design-width_px": 1011,
        "design-height_px": 638,
        "design-dpi": 300,
        "design-bleed_mm": "0.0",
        "design-logo_width_px": 300,
        "design-front_text": "A distinct loyalty brand",
        "design-back_text": "Testowa 1\n+48 500 000 000",
        "design-foreground_color": "#000000",
        "design-panel_color": "#FFFFFF",
        "design-barcode_foreground_color": "#000000",
        "design-barcode_background_color": "#FFFFFF",
        "design-font_family": "barlow",
    }


class CardDesignMigrationBaselineTests(TestCase):
    def test_marta_design_references_legacy_assets_without_replacing_them(self):
        tenant = default_tenant()
        design = tenant.card_designs.get(version=1)

        self.assertEqual(design.layout_preset, CardDesign.LayoutPreset.MARTA_LEGACY)
        self.assertEqual(design.background_source.name, "Marta Banaszek - Obraz II.jpg")
        self.assertEqual(design.logo.name, "logo_atelier_cafe.png")
        self.assertEqual(design.width_px, 1011)
        self.assertEqual(design.height_px, 638)
        self.assertEqual(design.dpi, 300)
        self.assertEqual(tenant.card_batches.get().design, design)

    def test_phase_three_backfill_verifier_is_read_only(self):
        output = StringIO()

        call_command(
            "verify_card_design_backfill",
            expect_designs=1,
            expect_brand_revisions=1,
            expect_wallets=0,
            expect_linked_batches=1,
            stdout=output,
        )

        self.assertEqual(json.loads(output.getvalue())["status"], "ok")


class CardRendererGoldenTests(TestCase):
    def test_marta_compatible_layout_is_deterministic_and_tenant_distinct(self):
        background = image_bytes("#F4EBDD")
        logo = image_bytes("#FFFFFF00", size=(500, 180), logo=True)
        spec = DesignSpec(
            tenant_slug="marta-banaszek-atelier-cafe",
            card_prefix="MB",
            name="Golden Marta",
            layout_preset=CardDesign.LayoutPreset.MARTA_LEGACY,
            crop_mode=CardDesign.CropMode.DETERMINISTIC,
            focal_x=50,
            focal_y=50,
            width_px=1011,
            height_px=638,
            dpi=300,
            bleed_mm="0.0",
            logo_width_px=576,
            front_text="where coffee meets fashion",
            back_text="ul. Wąwozowa 8/lokal 3a\ntel.: +48 519 727 253",
            foreground_color="#000000",
            panel_color="#FFFFFF",
            barcode_foreground_color="#000000",
            barcode_background_color="#FFFFFF",
            font_family="barlow",
            checksum="1" * 64,
            background_bytes=background,
            logo_bytes=logo,
        )

        first = render_card(spec, "MB-1")
        second = render_card(spec, "MB-1")
        other = render_card(
            replace(
                spec,
                tenant_slug="second-cafe",
                card_prefix="SC",
                front_text="A distinct second tenant",
                foreground_color="#173A5E",
                checksum="2" * 64,
            ),
            "SC-1",
        )

        self.assertEqual(first.front, second.front)
        self.assertEqual(first.back, second.back)
        # JPEG encoder output can differ across libjpeg builds and CPU
        # architectures even when the rendered image is equivalent. Assert the
        # deterministic crop plan and same-process byte stability instead of an
        # environment-specific encoded-file digest.
        self.assertEqual(first.crop_box, (0, 12, 1011, 650))
        self.assertEqual(bytes_sha256(first.front), bytes_sha256(second.front))
        self.assertNotEqual(first.front, other.front)
        self.assertNotEqual(first.back, other.back)
        with Image.open(BytesIO(first.front)) as image:
            self.assertEqual(image.size, (1011, 638))
            self.assertEqual(image.info.get("dpi"), (300, 300))


class CardArtifactServiceTests(TestCase):
    def test_retries_publish_new_paths_and_preserve_existing_bytes(self):
        with TemporaryDirectory() as directory, override_settings(MEDIA_ROOT=directory):
            tenant = create_tenant()
            design = create_design(tenant)
            card = create_physical_card(tenant, number=12)

            first = generate_card_artifacts(design=design, physical_card=card)
            first_paths = [Path(directory) / artifact.storage_path for artifact in first]
            first_bytes = [path.read_bytes() for path in first_paths]
            shared_render = render_card(spec_from_design(design), card.code)
            second = generate_card_artifacts(design=design, physical_card=card)

            self.assertTrue(all(path.is_file() for path in first_paths))
            self.assertEqual(first_bytes, [path.read_bytes() for path in first_paths])
            front_artifact = next(a for a in first if a.kind == CardArtifact.Kind.CARD_FRONT)
            self.assertEqual(
                (Path(directory) / front_artifact.storage_path).read_bytes(),
                shared_render.front,
            )
            self.assertTrue(set(a.storage_path for a in first).isdisjoint(a.storage_path for a in second))
            self.assertEqual(CardArtifact.objects.filter(tenant=tenant).count(), 8)
            manifest = next(a for a in first if a.kind == CardArtifact.Kind.MANIFEST)
            payload = json.loads((Path(directory) / manifest.storage_path).read_text())
            self.assertEqual(payload["design_checksum"], design.design_checksum)
            self.assertEqual(payload["card_code"], "SC-12")

    def test_published_design_record_cannot_be_rewritten(self):
        with TemporaryDirectory() as directory, override_settings(MEDIA_ROOT=directory):
            design = create_design(create_tenant())
            design.name = "Changed in place"
            with self.assertRaises(ValidationError):
                design.save()


class CardDesignPortalTests(TestCase):
    def setUp(self):
        self.tenant = create_tenant()
        self.owner = create_tenant_owner(self.tenant)
        self.url = reverse(
            "dotykacka:card_design_settings",
            args=[self.tenant.slug],
        )
        self.client.force_login(self.owner)

    def files(self):
        return {
            "design-background_image": upload("background.png", image_bytes("#E9DCC9")),
            "design-logo_image": upload(
                "logo.png",
                image_bytes("#FFFFFF00", size=(500, 180), logo=True),
            ),
        }

    def test_htmx_proof_does_not_publish_and_normal_publish_creates_version(self):
        with TemporaryDirectory() as directory, override_settings(MEDIA_ROOT=directory):
            proof_response = self.client.post(
                self.url,
                {**design_post_data(self.tenant), "action": "proof", **self.files()},
                HTTP_HX_REQUEST="true",
            )

            self.assertEqual(proof_response.status_code, 200)
            self.assertContains(proof_response, "data:image/jpeg;base64,")
            self.assertFalse(CardDesign.objects.filter(tenant=self.tenant).exists())

            publish_response = self.client.post(
                self.url,
                {**design_post_data(self.tenant), "action": "publish", **self.files()},
            )

            self.assertEqual(publish_response.status_code, 302)
            design = CardDesign.objects.get(tenant=self.tenant, version=1)
            self.assertEqual(design.brand_revision.public_name, self.tenant.name)
            self.assertTrue(
                design.background_source.name.startswith(
                    "tenants/second-cafe/designs/v0001/assets/background-"
                )
            )
            self.assertNotIn("background.png", design.background_source.name)
            self.assertEqual(
                CardArtifact.objects.filter(tenant=self.tenant, design=design).count(),
                4,
            )
            self.assertTrue(
                AuditEvent.objects.filter(
                    tenant=self.tenant,
                    action="card_design.published",
                ).exists()
            )

    def test_cross_tenant_member_cannot_open_settings_or_download_artifact(self):
        with TemporaryDirectory() as directory, override_settings(MEDIA_ROOT=directory):
            design = create_design(self.tenant)
            card = create_physical_card(self.tenant, number=12)
            artifact = generate_card_artifacts(design=design, physical_card=card)[0]
            download_url = reverse(
                "dotykacka:card_artifact_download",
                args=[self.tenant.slug, artifact.pk],
            )
            allowed = self.client.get(download_url)
            self.assertEqual(allowed.status_code, 200)
            self.assertIn("attachment", allowed.headers["Content-Disposition"])
            other = create_tenant(name="Other", slug="other", card_prefix="OT")
            other_owner = create_tenant_owner(other, username="other-owner")
            self.client.force_login(other_owner)

            self.assertEqual(self.client.get(self.url).status_code, 403)
            self.assertEqual(self.client.get(download_url).status_code, 403)


class CardGeneratorCommandTests(TestCase):
    def test_dry_run_is_bounded_and_writes_no_artifact(self):
        with TemporaryDirectory() as directory, override_settings(MEDIA_ROOT=directory):
            tenant = create_tenant()
            design = create_design(tenant)
            create_physical_card(tenant, number=12)
            output = StringIO()

            call_command(
                "generate_card_artifacts",
                tenant=tenant.slug,
                design_version=design.version,
                card_codes=["SC-12"],
                dry_run=True,
                stdout=output,
            )

            result = json.loads(output.getvalue())
            self.assertEqual(result["status"], "planned")
            self.assertEqual(result["cards"], ["SC-12"])
            self.assertFalse(CardArtifact.objects.filter(tenant=tenant).exists())
