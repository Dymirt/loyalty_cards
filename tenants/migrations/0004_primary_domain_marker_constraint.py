from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("tenants", "0003_backfill_primary_domain_marker"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="tenantdomain",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(is_primary=False, primary_for_tenant__isnull=True)
                    | models.Q(is_primary=True, primary_for_tenant=models.F("tenant"))
                ),
                name="tenant_domain_primary_marker_matches",
            ),
        )
    ]
