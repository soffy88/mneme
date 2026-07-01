"""Render a Jinja2 template string with the given context."""

from __future__ import annotations

from typing import Any

import jinja2

from oprim._exceptions import OprimError


def template_render(
    *,
    template: str,
    context: dict[str, Any],
    strict: bool = True,
) -> str:
    """Render a Jinja2 template string with the given context.

    Args:
        template: Jinja2 template string (e.g. "Hello {{ name }}")
        context: Variables to inject into the template
        strict: If True, undefined variables raise OprimError. If False, render as-is.

    Returns:
        Rendered string

    Raises:
        OprimError: Undefined variable (strict=True) or invalid template syntax

    Example:
        >>> template_render(template="Hello {{ name }}", context={"name": "Wiki"})
        'Hello Wiki'
    """
    undefined_cls = jinja2.StrictUndefined if strict else jinja2.Undefined
    env = jinja2.Environment(undefined=undefined_cls)

    try:
        tmpl = env.from_string(template)
    except jinja2.TemplateSyntaxError as e:
        raise OprimError(f"template_syntax_error: {e}") from e

    try:
        return tmpl.render(**context)
    except jinja2.UndefinedError as e:
        raise OprimError(f"undefined_variable: {e}") from e
