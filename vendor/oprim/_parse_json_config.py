"""Parse JSON/JSONC config strings into plain dicts."""
from __future__ import annotations

import json
import re
from typing import Any


def _strip_jsonc_comments(text: str) -> str:
    """Remove single-line (//) and block (/* */) comments from JSONC text."""
    # Remove block comments first
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    # Remove single-line comments (not inside strings — best-effort)
    text = re.sub(r"//[^\n]*", "", text)
    return text


def _strip_trailing_commas(text: str) -> str:
    """Remove trailing commas before } or ] (basic JSONC support)."""
    return re.sub(r",\s*([}\]])", r"\1", text)


def parse_json_config(raw: str) -> dict[str, Any]:
    """Parse a JSON or JSONC string and return a plain dict.

    Processing steps:
        1. Return {} for empty / whitespace-only input.
        2. Strip JSONC comments.
        3. Strip trailing commas before } or ].
        4. Parse with json.loads.
        5. Raise ValueError for non-object top-level values.
        6. Remove the ``$schema`` key from the result dict.

    Raises:
        ValueError: if the top-level value is not an object, or if the
                    JSON is syntactically invalid.
    """
    if not raw or not raw.strip():
        return {}

    cleaned = _strip_jsonc_comments(raw)
    cleaned = _strip_trailing_commas(cleaned)

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in config: {exc}") from exc

    if not isinstance(parsed, dict):
        raise ValueError(
            f"Config must be a JSON object, got {type(parsed).__name__}"
        )

    parsed.pop("$schema", None)
    return parsed
