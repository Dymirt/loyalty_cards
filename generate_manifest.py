"""Compatibility wrapper around the shared Apple manifest implementation."""

import sys

from dotykacka.services.apple_wallet import generate_manifest


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python generate_manifest.py PASS_DIRECTORY")
    generate_manifest(sys.argv[1])
