from django.db import migrations


def backfill_primary_domain_marker(apps, schema_editor):
    TenantDomain = apps.get_model("tenants", "TenantDomain")
    seen_tenant_ids = set()
    for domain in TenantDomain.objects.filter(is_primary=True).order_by("pk"):
        if domain.tenant_id in seen_tenant_ids:
            raise RuntimeError(
                "More than one primary registration domain exists for a tenant."
            )
        seen_tenant_ids.add(domain.tenant_id)
        if domain.primary_for_tenant_id not in (None, domain.tenant_id):
            raise RuntimeError("A primary registration-domain marker is inconsistent.")
        if domain.primary_for_tenant_id is None:
            TenantDomain.objects.filter(pk=domain.pk).update(
                primary_for_tenant_id=domain.tenant_id
            )


class Migration(migrations.Migration):
    dependencies = [
        ("tenants", "0002_portable_primary_domain"),
    ]

    operations = [
        migrations.RunPython(
            backfill_primary_domain_marker,
            reverse_code=migrations.RunPython.noop,
        )
    ]
