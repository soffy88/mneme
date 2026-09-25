"""Thin compatibility entry point for the canonical vendored Echo Loop."""

from vendor.oprim.echo_loop import *  # noqa: F401,F403

__all__ = [name for name in globals() if not name.startswith("_")]
