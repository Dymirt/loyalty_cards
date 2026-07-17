"""Compatibility entry point for the former standalone random crop loop.

Cropping is now deterministic and persisted through the shared card-artifact
service. Use the bounded Django command documented below.
"""

import sys

from django.core.management import execute_from_command_line


if __name__ == "__main__":
    execute_from_command_line(["manage.py", "generate_card_artifacts", *sys.argv[1:]])
