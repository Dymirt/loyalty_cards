from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = [("dotykacka", "0013_backfill_card_designs")]

    operations = [
        migrations.CreateModel(
            name="CropPlan",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("card_code", models.CharField(max_length=60)),
                ("seed", models.CharField(max_length=64)),
                ("source_sha256", models.CharField(max_length=64)),
                ("source_width", models.PositiveIntegerField()),
                ("source_height", models.PositiveIntegerField()),
                ("resized_width", models.PositiveIntegerField()),
                ("resized_height", models.PositiveIntegerField()),
                ("crop_left", models.PositiveIntegerField()),
                ("crop_top", models.PositiveIntegerField()),
                ("crop_right", models.PositiveIntegerField()),
                ("crop_bottom", models.PositiveIntegerField()),
                ("render_version", models.CharField(default="card-artwork-v1", max_length=40)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("design", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="crop_plans", to="dotykacka.carddesign")),
                ("physical_card", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="crop_plans", to="dotykacka.physicalcard")),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="crop_plans", to="dotykacka.tenant")),
            ],
            options={"ordering": ("design_id", "card_code")},
        ),
        migrations.AddConstraint(
            model_name="cropplan",
            constraint=models.UniqueConstraint(fields=("design", "card_code", "render_version"), name="unique_design_card_crop_plan"),
        ),
    ]
