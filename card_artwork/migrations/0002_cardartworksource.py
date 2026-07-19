from pathlib import Path

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def backfill_artwork_sources(apps, schema_editor):
    CardArtworkSource = apps.get_model("card_artwork", "CardArtworkSource")
    CardDesign = apps.get_model("dotykacka", "CardDesign")

    seen = set()
    for design in CardDesign.objects.exclude(background_source="").order_by(
        "tenant_id", "version"
    ):
        image_name = str(design.background_source)
        key = (design.tenant_id, image_name)
        if key in seen:
            continue
        seen.add(key)
        filename = Path(image_name).name
        CardArtworkSource.objects.create(
            tenant_id=design.tenant_id,
            name=filename,
            image=image_name,
            created_by_id=design.created_by_id,
        )

        # Marta's original 600-card set used both masters. The first master was
        # never linked to CardDesign, so preserve it as an additional choice.
        if filename == "Marta Banaszek - Obraz II.jpg":
            first_name = "Marta Banaszek - Obraz.jpg"
            first_key = (design.tenant_id, first_name)
            if first_key not in seen:
                seen.add(first_key)
                CardArtworkSource.objects.create(
                    tenant_id=design.tenant_id,
                    name=first_name,
                    image=first_name,
                    created_by_id=design.created_by_id,
                )


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("card_artwork", "0001_crop_plan"),
        ("dotykacka", "0015_alter_cardartifact_kind_alter_cardbatch_status_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="CardArtworkSource",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("name", models.CharField(max_length=160)),
                ("image", models.ImageField(max_length=500, upload_to="")),
                ("source_sha256", models.CharField(blank=True, max_length=64)),
                ("width_px", models.PositiveIntegerField(blank=True, null=True)),
                ("height_px", models.PositiveIntegerField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="created_card_artwork_sources",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "tenant",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="card_artwork_sources",
                        to="dotykacka.tenant",
                    ),
                ),
            ],
            options={"ordering": ("created_at", "id")},
        ),
        migrations.RunPython(backfill_artwork_sources, migrations.RunPython.noop),
    ]
