"""Thin compatibility entry point for the canonical vendored Echo Loop skill."""

from vendor.oskill.echo_loop_skill import *  # noqa: F401,F403

__all__ = [name for name in globals() if not name.startswith("_")]
