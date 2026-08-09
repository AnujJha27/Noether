"""Compatibility entry point for the legacy V1 CLI."""

from .legacy.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
