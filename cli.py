"""Compatibility launcher for the canonical CLI implementation."""
from app.cli import main

__all__ = ["main"]

if __name__ == "__main__":
    raise SystemExit(main())
