"""Read-only inventory and structural checks for safe Django app extraction."""

import os

from django.apps import apps
from django.conf import settings
from django.contrib import admin
from django.contrib.admin.models import LogEntry
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.core.management import get_commands
from django.db import DatabaseError, connection
from django.db.migrations.recorder import MigrationRecorder
from django.db.models import Count
from django.urls import URLPattern, URLResolver, get_resolver

from .architecture import TARGET_APPS


LEGACY_MODEL_TABLES = {
    "dotykacka.accesstoken": "dotykacka_accesstoken",
    "dotykacka.auditevent": "dotykacka_auditevent",
    "dotykacka.cardartifact": "dotykacka_cardartifact",
    "dotykacka.cardbatch": "dotykacka_cardbatch",
    "dotykacka.carddesign": "dotykacka_carddesign",
    "dotykacka.integrationconnection": "dotykacka_integrationconnection",
    "dotykacka.klient": "dotykacka_klient",
    "dotykacka.physicalcard": "dotykacka_physicalcard",
    "dotykacka.tenant": "dotykacka_tenant",
    "dotykacka.tenantbrand": "dotykacka_tenantbrand",
    "dotykacka.tenantbrandrevision": "dotykacka_tenantbrandrevision",
    "dotykacka.tenantmembership": "dotykacka_tenantmembership",
    "dotykacka.walletpass": "dotykacka_walletpass",
}

EXTRACTED_MODEL_TABLES = {
    "billing.billingperiod": "billing_billingperiod",
    "billing.cardpack": "billing_cardpack",
    "billing.cardpackallocation": "billing_cardpackallocation",
    "billing.cardpricetier": "billing_cardpricetier",
    "billing.entitlementpolicy": "billing_entitlementpolicy",
    "billing.plan": "billing_plan",
    "billing.planversion": "billing_planversion",
    "billing.pricebook": "billing_pricebook",
    "billing.pricebookversion": "billing_pricebookversion",
    "billing.printquoteconsumption": "billing_printquoteconsumption",
    "billing.quote": "billing_quote",
    "billing.quoteline": "billing_quoteline",
    "billing.tenantsubscription": "billing_tenantsubscription",
    "billing.usageevent": "billing_usageevent",
    "card_artwork.cropplan": "card_artwork_cropplan",
    "communications.communicationdelivery": "communications_communicationdelivery",
    "customers.consentrecord": "customers_consentrecord",
    "customers.customerexternalidentity": "customers_customerexternalidentity",
    "integrations.integrationjob": "integrations_integrationjob",
    "marketing.marketinglead": "marketing_marketinglead",
    "operations.operationalalert": "operations_operationalalert",
    "operations.operationalalertevent": "operations_operationalalertevent",
    "operations.ratelimitbucket": "operations_ratelimitbucket",
    "operations.workerheartbeat": "operations_workerheartbeat",
    "tenants.tenantdomain": "tenants_tenantdomain",
    "enrollment.enrollment": "enrollment_enrollment",
    "enrollment.enrollmentaccesslink": "enrollment_enrollmentaccesslink",
    "enrollment.enrollmentevent": "enrollment_enrollmentevent",
    "enrollment.enrollmentfollowup": "enrollment_enrollmentfollowup",
    "pos_dotykacka.dotykackaaccesstoken": "pos_dotykacka_dotykackaaccesstoken",
    "pos_dotykacka.dotykackaconnectstate": "pos_dotykacka_dotykackaconnectstate",
    "printing.fulfillmentevent": "printing_fulfillmentevent",
    "printing.printjob": "printing_printjob",
    "printing.printpackage": "printing_printpackage",
    "printing.printrequest": "printing_printrequest",
    "printing.printrequestevent": "printing_printrequestevent",
    "printing.printrun": "printing_printrun",
    "printing.printruncard": "printing_printruncard",
}

LEGACY_ADMIN_MODELS = {
    "dotykacka.auditevent",
    "dotykacka.cardartifact",
    "dotykacka.cardbatch",
    "dotykacka.carddesign",
    "dotykacka.integrationconnection",
    "dotykacka.klient",
    "dotykacka.physicalcard",
    "dotykacka.tenant",
    "dotykacka.tenantbrand",
    "dotykacka.tenantbrandrevision",
    "dotykacka.tenantmembership",
    "dotykacka.walletpass",
}

LEGACY_COMMANDS = {
    "generate_card_artifacts",
    "generate_wallet_passes",
    "preflight_legacy_inventory",
    "verify_card_design_backfill",
    "verify_marta_backfill",
}

LEGACY_URL_NAMES = {
    "index",
    "login",
    "logout",
    "turnkey_compat:index",
    "dotykacka:acces_token",
    "dotykacka:customers",
    "dotykacka:register",
    "dotykacka:tenant_register",
    "dotykacka:tenant_portal",
    "dotykacka:integration_settings",
    "dotykacka:card_design_settings",
    "dotykacka:card_artifact_download",
    "dotykacka:platform_print_center",
    "dotykacka:send_pass",
    "dotykacka:add_all_to_brevo",
    "dotykacka:generate_jwt_passes",
    "dotykacka:send_passes_to_all",
}

EXTRACTED_URL_NAMES = {
    "card_artwork:artifact_download",
    "card_artwork:settings",
    "cards:platform_print_center",
    "customers:list",
    "enrollment:register",
    "enrollment:tenant_register",
    "enrollment:public_status",
    "enrollment:public_apple_pass",
    "enrollment:manage",
    "enrollment:request_domain",
    "enrollment:detail",
    "enrollment:ensure_followups",
    "enrollment:resend_email",
    "enrollment:retry_followup",
    "tenants:portal",
    "integrations:settings",
    "integrations:test",
    "integrations:system_connections",
    "integrations:test_system_connection",
    "marketing:home",
    "marketing:features",
    "marketing:integrations",
    "marketing:pricing",
    "marketing:contact",
    "marketing:contact_thanks",
    "marketing:privacy",
    "marketing:terms",
    "health_live",
    "health_ready",
    "protected_media",
    "operations:dashboard",
    "operations:acknowledge",
    "operations:resolve",
    "pos_dotykacka:connect",
    "pos_dotykacka:disconnect",
    "pos_dotykacka:callback",
    "billing:tenant",
    "billing:create_quote",
    "billing:accept_quote",
    "billing:platform",
    "printing:tenant",
    "printing:submit",
    "printing:platform_queue",
    "printing:platform_detail",
    "printing:approve",
    "printing:reject",
    "printing:allocate",
    "printing:cancel",
    "printing:fulfill",
    "printing:run_status",
    "printing:package_download",
    "printing:correct_event",
    "printing:legacy_preview",
    "printing:legacy_confirm",
}

MARTA_EXPECTED_ROWS = {
    "dotykacka.cardbatch": 1,
    "dotykacka.carddesign": 1,
    "dotykacka.integrationconnection": 3,
    "dotykacka.klient": 267,
    "dotykacka.physicalcard": 600,
    "dotykacka.tenant": 1,
    "dotykacka.tenantbrand": 1,
    "dotykacka.tenantbrandrevision": 1,
    "dotykacka.tenantmembership": 1,
    "dotykacka.walletpass": 267,
}

LEGACY_DOTYKACKA_MIGRATIONS = {
    "0001_initial",
    "0002_alter_accesstoken_token",
    "0003_klient",
    "0004_alter_klient_klient_id",
    "0005_auto_20250519_1454",
    "0006_klient_google_jwt_url",
    "0007_alter_klient_google_jwt_url",
    "0008_alter_klient_klient_id_unique",
    "0009_tenant_foundation",
    "0010_backfill_marta_tenant",
    "0011_require_tenant_ownership",
    "0012_card_design_foundation",
    "0013_backfill_card_designs",
    "0014_promote_dotykacka_refresh_tokens",
    "0015_alter_cardartifact_kind_alter_cardbatch_status_and_more",
}

EXTRACTED_MIGRATIONS = {
    ("card_artwork", "0001_crop_plan"),
    ("customers", "0001_customer_domain_models"),
    ("customers", "0002_external_identity_sync_status"),
    ("customers", "0003_external_identity_pending_remote_id"),
    ("customers", "0004_alter_customerexternalidentity_sync_status"),
    ("integrations", "0001_initial"),
    ("integrations", "0002_alter_integrationjob_status"),
    ("marketing", "0001_initial"),
    ("operations", "0001_initial"),
    ("operations", "0002_alter_operationalalert_severity_and_more"),
    ("pos_dotykacka", "0001_initial"),
    ("billing", "0001_initial"),
    ("billing", "0002_printquoteconsumption"),
    ("billing", "0003_alter_billingperiod_status_and_more"),
    ("billing", "0004_alter_planversion_tax_rate"),
    ("printing", "0001_initial"),
    ("printing", "0002_alter_fulfillmentevent_event_type_and_more"),
    ("communications", "0001_initial"),
    ("communications", "0002_alter_communicationdelivery_channel_and_more"),
    ("enrollment", "0001_initial"),
    ("enrollment", "0002_alter_enrollmentaccesslink_purpose_and_more"),
    ("tenants", "0001_initial"),
    ("tenants", "0002_portable_primary_domain"),
    ("tenants", "0003_backfill_primary_domain_marker"),
    ("tenants", "0004_primary_domain_marker_constraint"),
    ("tenants", "0005_alter_tenantdomain_status"),
}


def _walk_urls(patterns=None, prefix="", namespaces=()):
    patterns = patterns if patterns is not None else get_resolver().url_patterns
    inventory = []
    for entry in patterns:
        route = f"{prefix}{entry.pattern}"
        if isinstance(entry, URLResolver):
            namespace = entry.namespace or entry.app_name
            child_namespaces = namespaces + ((namespace,) if namespace else ())
            inventory.extend(
                _walk_urls(entry.url_patterns, route, child_namespaces)
            )
        elif isinstance(entry, URLPattern):
            qualified_name = entry.name
            if qualified_name and namespaces:
                qualified_name = ":".join((*namespaces, qualified_name))
            inventory.append(
                {
                    "route": route,
                    "name": qualified_name or "",
                    "callback": entry.lookup_str,
                }
            )
    return inventory


def _action_name(action):
    if isinstance(action, str):
        return action
    return getattr(action, "__name__", action.__class__.__name__)


def collect_extraction_inventory(*, include_rows=True):
    """Collect only aggregate/schema metadata; no record values or secrets."""

    database_tables = set(connection.introspection.table_names())
    model_inventory = []
    for model in apps.get_models():
        rows = None
        if include_rows and model._meta.db_table in database_tables:
            try:
                rows = model._base_manager.count()
            except DatabaseError:
                rows = None
        model_inventory.append(
            {
                "label": model._meta.label_lower,
                "table": model._meta.db_table,
                "rows": rows,
            }
        )

    content_types = []
    if ContentType._meta.db_table in database_tables:
        content_types = [
            {"app_label": app_label, "model": model}
            for app_label, model in ContentType.objects.order_by(
                "app_label", "model"
            ).values_list("app_label", "model")
        ]

    permissions = []
    if Permission._meta.db_table in database_tables:
        permissions = [
            {"app_label": app_label, "model": model, "codename": codename}
            for app_label, model, codename in Permission.objects.order_by(
                "content_type__app_label", "content_type__model", "codename"
            ).values_list(
                "content_type__app_label",
                "content_type__model",
                "codename",
            )
        ]

    migrations = []
    if MigrationRecorder.Migration._meta.db_table in database_tables:
        migrations = [
            {"app": app_label, "name": name}
            for app_label, name in MigrationRecorder.Migration.objects.order_by(
                "app", "name"
            ).values_list("app", "name")
        ]

    admin_log_references = []
    if LogEntry._meta.db_table in database_tables:
        admin_log_references = [
            {
                "app_label": app_label or "",
                "model": model or "",
                "rows": rows,
            }
            for app_label, model, rows in LogEntry.objects.values(
                "content_type__app_label",
                "content_type__model",
            )
            .annotate(rows=Count("id"))
            .order_by("content_type__app_label", "content_type__model")
            .values_list(
                "content_type__app_label",
                "content_type__model",
                "rows",
            )
        ]

    admin_models = []
    for model, model_admin in admin.site._registry.items():
        declared_actions = model_admin.actions or ()
        admin_models.append(
            {
                "model": model._meta.label_lower,
                "admin_class": (
                    f"{model_admin.__class__.__module__}."
                    f"{model_admin.__class__.__name__}"
                ),
                "declared_actions": sorted(_action_name(a) for a in declared_actions),
            }
        )

    return {
        "schema_version": 8,
        "settings_module": os.environ.get("DJANGO_SETTINGS_MODULE", ""),
        "root_urlconf": settings.ROOT_URLCONF,
        "wsgi_application": settings.WSGI_APPLICATION,
        "asgi_application": settings.ASGI_APPLICATION,
        "test_runner": settings.TEST_RUNNER,
        "installed_apps": [config.name for config in apps.get_app_configs()],
        "models": sorted(model_inventory, key=lambda item: item["label"]),
        "database_tables": sorted(database_tables),
        "content_types": content_types,
        "permissions": permissions,
        "migrations": migrations,
        "urls": sorted(
            _walk_urls(), key=lambda item: (item["route"], item["name"])
        ),
        "commands": [
            {"name": name, "provider": str(provider)}
            for name, provider in sorted(get_commands().items())
        ],
        "admin": {
            "models": sorted(admin_models, key=lambda item: item["model"]),
            "site_actions": sorted(admin.site._actions),
            "log_references": admin_log_references,
        },
    }


def structural_errors(inventory, *, expect_marta=False):
    errors = []
    models = {item["label"]: item for item in inventory["models"]}
    for label, table in LEGACY_MODEL_TABLES.items():
        if label not in models:
            errors.append(f"Missing legacy model {label}.")
        elif models[label]["table"] != table:
            errors.append(
                f"Legacy model {label} moved from {table} to {models[label]['table']}."
            )
    actual_legacy_models = {
        label for label in models if label.startswith("dotykacka.")
    }
    if actual_legacy_models != set(LEGACY_MODEL_TABLES):
        errors.append("The legacy dotykacka model-label inventory changed.")

    target_app_set = set(TARGET_APPS)
    actual_target_models = {
        label: models[label]["table"]
        for label in models
        if label.split(".", 1)[0] in target_app_set
    }
    if actual_target_models != EXTRACTED_MODEL_TABLES:
        errors.append(
            "The extracted destination-model/table inventory changed."
        )

    content_types = {
        (item["app_label"], item["model"]) for item in inventory["content_types"]
    }
    for label in LEGACY_MODEL_TABLES:
        app_label, model = label.split(".", 1)
        if (app_label, model) not in content_types:
            errors.append(f"Missing content type {label}.")
    actual_legacy_content_types = {
        f"{app_label}.{model}"
        for app_label, model in content_types
        if app_label == "dotykacka"
    }
    if actual_legacy_content_types != set(LEGACY_MODEL_TABLES):
        errors.append("The legacy dotykacka content-type inventory changed.")
    actual_target_content_types = {
        f"{app_label}.{model}"
        for app_label, model in content_types
        if app_label in target_app_set
    }
    if actual_target_content_types != set(EXTRACTED_MODEL_TABLES):
        errors.append("The extracted destination content-type inventory changed.")

    permission_keys = {
        (item["app_label"], item["model"], item["codename"])
        for item in inventory["permissions"]
    }
    for label in LEGACY_MODEL_TABLES:
        app_label, model = label.split(".", 1)
        for action in ("add", "change", "delete", "view"):
            key = (app_label, model, f"{action}_{model}")
            if key not in permission_keys:
                errors.append(f"Missing permission {app_label}.{key[2]}.")
    expected_target_permissions = {
        (app_label, model, f"{action}_{model}")
        for app_label, model in (label.split(".", 1) for label in EXTRACTED_MODEL_TABLES)
        for action in ("add", "change", "delete", "view")
    }
    actual_target_permissions = {
        key for key in permission_keys if key[0] in target_app_set
    }
    if actual_target_permissions != expected_target_permissions:
        errors.append("The extracted destination permission inventory changed.")

    expected_legacy_permissions = {
        ("dotykacka", model, f"{action}_{model}")
        for _, model in (label.split(".", 1) for label in LEGACY_MODEL_TABLES)
        for action in ("add", "change", "delete", "view")
    }
    actual_legacy_permissions = {
        key for key in permission_keys if key[0] == "dotykacka"
    }
    if actual_legacy_permissions != expected_legacy_permissions:
        errors.append("The legacy dotykacka permission inventory changed.")

    applied_legacy_migrations = {
        item["name"]
        for item in inventory["migrations"]
        if item["app"] == "dotykacka"
    }
    if applied_legacy_migrations != LEGACY_DOTYKACKA_MIGRATIONS:
        errors.append("The applied dotykacka migration inventory changed.")
    applied_extracted_migrations = {
        (item["app"], item["name"])
        for item in inventory["migrations"]
        if item["app"] in {
            "billing",
            "card_artwork",
            "communications",
            "customers",
            "enrollment",
            "integrations",
            "marketing",
            "operations",
            "pos_dotykacka",
            "printing",
            "tenants",
        }
    }
    if applied_extracted_migrations != EXTRACTED_MIGRATIONS:
        errors.append("The applied extracted-app migration inventory changed.")

    command_names = {item["name"] for item in inventory["commands"]}
    missing_commands = sorted(LEGACY_COMMANDS - command_names)
    if missing_commands:
        errors.append("Missing legacy commands: " + ", ".join(missing_commands))
    command_providers = {item["name"]: item["provider"] for item in inventory["commands"]}
    if command_providers.get("generate_card_artifacts") != "card_artwork":
        errors.append("The card artifact command is not owned by card_artwork.")
    if command_providers.get("generate_wallet_passes") != "wallets":
        errors.append("The Wallet command is not owned by wallets.")
    if command_providers.get("run_integration_worker") != "integrations":
        errors.append("The integration worker command is not owned by integrations.")
    if command_providers.get("run_print_worker") != "printing":
        errors.append("The print worker command is not owned by printing.")
    for command_name in (
        "check_worker_heartbeat",
        "create_platform_backup",
        "report_marketing_retention",
        "report_platform_health",
        "run_operational_monitor",
        "verify_platform_backup",
        "verify_saas_rollout",
    ):
        if command_providers.get(command_name) != "operations":
            errors.append(f"The {command_name} command is not owned by operations.")

    url_names = {item["name"] for item in inventory["urls"] if item["name"]}
    missing_urls = sorted(LEGACY_URL_NAMES - url_names)
    if missing_urls:
        errors.append("Missing legacy URL names: " + ", ".join(missing_urls))
    missing_extracted_urls = sorted(EXTRACTED_URL_NAMES - url_names)
    if missing_extracted_urls:
        errors.append(
            "Missing canonical extraction URLs: " + ", ".join(missing_extracted_urls)
        )

    admin_models = {item["model"] for item in inventory["admin"]["models"]}
    missing_admin_models = sorted(LEGACY_ADMIN_MODELS - admin_models)
    if missing_admin_models:
        errors.append(
            "Missing legacy admin registrations: " + ", ".join(missing_admin_models)
        )
    if inventory["admin"]["site_actions"] != ["delete_selected"]:
        errors.append("The global Django admin action inventory changed.")
    extracted_admin_models = set(EXTRACTED_MODEL_TABLES)
    if not extracted_admin_models.issubset(admin_models):
        errors.append("Missing extracted destination admin registrations.")

    if inventory["root_urlconf"] != "loyalty_platform.urls":
        errors.append("The active root URLconf is not loyalty_platform.urls.")
    if inventory["wsgi_application"] != "loyalty_platform.wsgi.application":
        errors.append("The active WSGI application was not renamed.")
    if inventory["asgi_application"] != "loyalty_platform.asgi.application":
        errors.append("The active ASGI application was not renamed.")
    if inventory["test_runner"] != "loyalty_platform.test_runner.NoExternalCallsDiscoverRunner":
        errors.append("The active test runner was not renamed.")

    installed_apps = set(inventory["installed_apps"])
    missing_apps = sorted(target_app_set - installed_apps)
    if missing_apps:
        errors.append("Missing target apps: " + ", ".join(missing_apps))

    if expect_marta:
        for label, expected in MARTA_EXPECTED_ROWS.items():
            actual = models.get(label, {}).get("rows")
            if actual != expected:
                errors.append(f"{label} rows: expected {expected}, found {actual}.")
        token_rows = models.get("dotykacka.accesstoken", {}).get("rows")
        if token_rows is None or token_rows < 261:
            errors.append(
                "dotykacka.accesstoken rows must preserve the 261-row migration baseline."
            )

    return errors
