"""Thin compatibility entry point for canonical vendored Echo Loop primitives."""

from vendor.oprim.echo_loop import *  # noqa: F401,F403

__all__ = [name for name in globals() if not name.startswith("_")]
