from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("customers", "0002_external_identity_sync_status")]

    operations = [
        migrations.AlterField(
            model_name="customerexternalidentity",
            name="remote_id",
            field=models.CharField(blank=True, max_length=240, null=True),
        )
    ]
