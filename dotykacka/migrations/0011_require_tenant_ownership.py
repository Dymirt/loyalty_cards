import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("dotykacka", "0010_backfill_marta_tenant")]
    operations = [
        migrations.AlterField(
            model_name="klient",
            name="tenant",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="customers",
                to="dotykacka.tenant",
            ),
        ),
        migrations.AlterField(
            model_name="accesstoken",
            name="connection",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="access_tokens",
                to="dotykacka.integrationconnection",
            ),
        ),
    ]
