from __future__ import annotations

import datetime
from typing import Any

from pydantic import BaseModel

from oskill._exceptions import OskillError


class TemplateVariableSpec(BaseModel):
    name: str
    source: str
    fixed_value: str | None = None


def render_template(
    template_content: str,
    variables_spec: list[TemplateVariableSpec],
    user_inputs: dict[str, Any] | None = None,
) -> str:
    """Render a template by replacing {{variable_name}} with evaluated values.

    Sources supported:
    - fixed: use fixed_value
    - user: use value from user_inputs
    - auto: supported names (date, datetime, time, weekday, year, month, day)

    Args:
        template_content: The template string.
        variables_spec: List of variable specifications.
        user_inputs: Dictionary of user-provided values.

    Returns:
        Rendered string.

    Raises:
        OskillError: if a required user input is missing, or source is unknown.

    Example:
        ```python
        spec = [
            TemplateVariableSpec(name="date", source="auto"),
            TemplateVariableSpec(name="name", source="user")
        ]
        rendered = render_template("Hello {{name}}, today is {{date}}", spec, {"name": "Alice"})
        assert "Alice" in rendered
        ```
    """
    user_inputs = user_inputs or {}
    rendered = template_content
    now = datetime.datetime.now()

    for var in variables_spec:
        val = ""
        if var.source == "fixed":
            val = var.fixed_value or ""
        elif var.source == "user":
            if var.name not in user_inputs:
                raise OskillError(f"Missing required user input: {var.name}")
            val = str(user_inputs[var.name])
        elif var.source == "auto":
            if var.name == "date":
                val = now.strftime("%Y-%m-%d")
            elif var.name == "datetime":
                val = now.strftime("%Y-%m-%d %H:%M:%S")
            elif var.name == "time":
                val = now.strftime("%H:%M:%S")
            elif var.name == "weekday":
                val = str(now.isoweekday())
            elif var.name == "year":
                val = str(now.year)
            elif var.name == "month":
                val = f"{now.month:02d}"
            elif var.name == "day":
                val = f"{now.day:02d}"
            else:
                raise OskillError(f"Unsupported auto variable: {var.name}")
        else:
            raise OskillError(f"Unknown source: {var.source}")

        rendered = rendered.replace(f"{{{{{var.name}}}}}", val)

    return rendered
