import json

from django.core.management.base import BaseCommand, CommandError

from core.extraction_inventory import (
    collect_extraction_inventory,
    structural_errors,
)


class Command(BaseCommand):
    help = (
        "Read-only report for model/table, content-type, permission, URL, command, "
        "admin, migration, and aggregate row-count extraction invariants."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--json",
            action="store_true",
            dest="as_json",
            help="Print the complete non-sensitive report as JSON.",
        )
        parser.add_argument(
            "--strict",
            action="store_true",
            help="Fail if a Phase 4 structural invariant changed.",
        )
        parser.add_argument(
            "--expect-marta",
            action="store_true",
            help="Also verify the stable first-tenant aggregate row counts.",
        )

    def handle(self, *args, **options):
        inventory = collect_extraction_inventory(include_rows=True)
        errors = structural_errors(
            inventory,
            expect_marta=options["expect_marta"],
        )
        inventory["verification"] = {
            "passed": not errors,
            "errors": errors,
            "marta_counts_checked": options["expect_marta"],
        }

        if options["as_json"]:
            self.stdout.write(json.dumps(inventory, indent=2, sort_keys=True))
        else:
            self.stdout.write(
                "Extraction inventory: "
                f"{len(inventory['models'])} models, "
                f"{len(inventory['content_types'])} content types, "
                f"{len(inventory['permissions'])} permissions, "
                f"{len(inventory['urls'])} URL patterns, "
                f"{len(inventory['commands'])} commands, "
                f"{len(inventory['admin']['models'])} admin registrations, "
                f"{len(inventory['admin']['log_references'])} admin-log reference groups."
            )
            if errors:
                for error in errors:
                    self.stdout.write(self.style.ERROR(f"- {error}"))
            else:
                self.stdout.write(self.style.SUCCESS("Extraction verification passed."))

        if options["strict"] and errors:
            raise CommandError(f"Extraction verification failed with {len(errors)} error(s).")
