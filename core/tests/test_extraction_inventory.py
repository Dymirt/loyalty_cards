import json
from io import StringIO

from django.apps import apps
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.test import TestCase

from core.architecture import TARGET_APPS
from core.extraction_inventory import (
    LEGACY_COMMANDS,
    LEGACY_MODEL_TABLES,
    LEGACY_URL_NAMES,
    collect_extraction_inventory,
    structural_errors,
)


class ExtractionInventoryTests(TestCase):
    def test_inventory_preserves_legacy_schema_and_exposes_new_apps(self):
        inventory = collect_extraction_inventory(include_rows=False)
        models = {item["label"]: item["table"] for item in inventory["models"]}

        self.assertEqual(
            {label: models[label] for label in LEGACY_MODEL_TABLES},
            LEGACY_MODEL_TABLES,
        )
        self.assertTrue(set(TARGET_APPS).issubset(inventory["installed_apps"]))
        self.assertFalse(
            any(
                item["app_label"] in TARGET_APPS
                for item in inventory["content_types"]
            )
        )
        self.assertFalse(
            any(
                item["app_label"] in TARGET_APPS
                for item in inventory["permissions"]
            )
        )
        self.assertTrue(
            LEGACY_COMMANDS.issubset(
                {item["name"] for item in inventory["commands"]}
            )
        )
        self.assertTrue(
            LEGACY_URL_NAMES.issubset(
                {item["name"] for item in inventory["urls"]}
            )
        )
        self.assertIn("log_references", inventory["admin"])
        self.assertFalse(
            any(
                item["app_label"] in TARGET_APPS
                for item in inventory["admin"]["log_references"]
            )
        )
        self.assertEqual(structural_errors(inventory), [])

    def test_inventory_collection_is_read_only(self):
        before_models = {
            model._meta.label_lower: model._base_manager.count()
            for model in apps.get_models()
            if model._meta.app_label == "dotykacka"
        }
        before_content_types = ContentType.objects.count()
        before_permissions = Permission.objects.count()

        collect_extraction_inventory(include_rows=True)

        after_models = {
            model._meta.label_lower: model._base_manager.count()
            for model in apps.get_models()
            if model._meta.app_label == "dotykacka"
        }
        self.assertEqual(after_models, before_models)
        self.assertEqual(ContentType.objects.count(), before_content_types)
        self.assertEqual(Permission.objects.count(), before_permissions)

    def test_management_command_supports_json_and_strict_verification(self):
        stdout = StringIO()
        call_command(
            "verify_app_extraction",
            as_json=True,
            strict=True,
            stdout=stdout,
        )
        report = json.loads(stdout.getvalue())

        self.assertTrue(report["verification"]["passed"])
        self.assertFalse(report["verification"]["marta_counts_checked"])
        self.assertEqual(report["verification"]["errors"], [])
