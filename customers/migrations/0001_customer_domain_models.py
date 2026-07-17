from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = [("dotykacka", "0013_backfill_card_designs")]

    operations = [
        migrations.CreateModel(
            name="ConsentRecord",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("purpose", models.CharField(max_length=80)),
                ("policy_version", models.CharField(max_length=80)),
                ("consent_text", models.TextField()),
                ("consent_text_sha256", models.CharField(max_length=64)),
                ("granted", models.BooleanField()),
                ("source", models.CharField(default="registration", max_length=40)),
                ("recorded_at", models.DateTimeField(auto_now_add=True)),
                ("revoked_at", models.DateTimeField(blank=True, null=True)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("customer", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="consent_records", to="dotykacka.klient")),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="consent_records", to="dotykacka.tenant")),
            ],
            options={"ordering": ("-recorded_at", "-pk")},
        ),
        migrations.CreateModel(
            name="CustomerExternalIdentity",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("provider", models.CharField(max_length=40)),
                ("remote_id", models.CharField(max_length=240)),
                ("remote_version", models.CharField(blank=True, max_length=240)),
                ("last_synced_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("customer", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="external_identities", to="dotykacka.klient")),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="customer_external_identities", to="dotykacka.tenant")),
            ],
            options={"ordering": ("provider", "customer_id")},
        ),
        migrations.AddConstraint(
            model_name="customerexternalidentity",
            constraint=models.UniqueConstraint(fields=("customer", "provider"), name="unique_customer_external_provider"),
        ),
        migrations.AddConstraint(
            model_name="customerexternalidentity",
            constraint=models.UniqueConstraint(fields=("tenant", "provider", "remote_id"), name="unique_tenant_provider_remote_customer"),
        ),
    ]
