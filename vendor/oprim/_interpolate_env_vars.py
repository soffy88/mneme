"""Recursively interpolate {env:VARNAME} placeholders in config dicts."""
from __future__ import annotations

import re
from typing import Any

_PLACEHOLDER_RE = re.compile(r"\{env:([^}]+)\}")


def _interpolate_str(value: str, env: dict[str, Any]) -> str:
    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in env:
            raise ValueError(f"env var {name} not set")
        return str(env[name])

    return _PLACEHOLDER_RE.sub(replace, value)


def _interpolate_value(value: Any, env: dict[str, Any]) -> Any:
    if isinstance(value, str):
        return _interpolate_str(value, env)
    if isinstance(value, dict):
        return {k: _interpolate_value(v, env) for k, v in value.items()}
    if isinstance(value, list):
        return [_interpolate_value(item, env) for item in value]
    return value


def interpolate_env_vars(config: dict[str, Any], *, env: dict[str, Any]) -> dict[str, Any]:
    """Recursively replace ``{env:VARNAME}`` in all string values of *config*.

    Traverses nested dicts and lists.  Returns a new dict; the original is
    not mutated.

    Raises:
        ValueError: if a referenced environment variable is not present in
                    *env*.
    """
    return {k: _interpolate_value(v, env) for k, v in config.items()}
