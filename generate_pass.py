"""Compatibility entry point for bounded tenant Wallet generation."""

import sys

from django.core.management import execute_from_command_line


if __name__ == "__main__":
    execute_from_command_line(["manage.py", "generate_wallet_passes", *sys.argv[1:]])
