"""Compatibility entry point for the shared physical-card generator."""

import sys

from django.core.management import execute_from_command_line


if __name__ == "__main__":
    execute_from_command_line(["manage.py", "generate_card_artifacts", *sys.argv[1:]])
