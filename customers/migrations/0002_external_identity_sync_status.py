from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("customers", "0001_customer_domain_models")]

    operations = [
        migrations.AddField(
            model_name="customerexternalidentity",
            name="last_attempted_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="customerexternalidentity",
            name="last_error_code",
            field=models.CharField(blank=True, max_length=80),
        ),
        migrations.AddField(
            model_name="customerexternalidentity",
            name="sync_status",
            field=models.CharField(
                choices=[
                    ("pending", "Pending"),
                    ("synced", "Synced"),
                    ("failed", "Failed"),
                    ("disabled", "Disabled"),
                ],
                db_index=True,
                default="pending",
                max_length=16,
            ),
        ),
    ]
