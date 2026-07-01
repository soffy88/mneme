"""Parse markdown agent definition files into AgentSpec objects."""
from __future__ import annotations

import re

import yaml

from oprim._hicode_types import AgentSpec

_VALID_MODES = {"primary", "subagent", "all"}

_FRONTMATTER_RE = re.compile(
    r"^---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|$)",
    re.DOTALL,
)


def parse_markdown_agent(content: str) -> AgentSpec:
    """Parse a markdown agent file and return an AgentSpec.

    Format::

        ---
        description: "Short description"
        mode: primary          # optional; default "primary"
        tools:                 # optional; default []
          - bash
          - read
        model: claude-3-5-sonnet  # optional; default ""
        ---

        System prompt body goes here …

    Raises:
        ValueError: if there is no frontmatter block, if ``description`` is
                    missing, or if ``mode`` is not one of
                    ``{primary, subagent, all}``.
    """
    match = _FRONTMATTER_RE.match(content)
    if not match:
        raise ValueError(
            "Agent file must begin with a YAML frontmatter block (--- ... ---)"
        )

    raw_yaml = match.group(1)
    body_start = match.end()
    system_prompt = content[body_start:]

    try:
        meta = yaml.safe_load(raw_yaml) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML frontmatter: {exc}") from exc

    if not isinstance(meta, dict):
        raise ValueError("Frontmatter must be a YAML mapping")

    description = meta.get("description")
    if not description:
        raise ValueError("Agent frontmatter must include a 'description' field")

    mode = str(meta.get("mode", "primary"))
    if mode not in _VALID_MODES:
        raise ValueError(
            f"Invalid agent mode {mode!r}; must be one of {sorted(_VALID_MODES)}"
        )

    raw_tools = meta.get("tools", [])
    tools: list[str] = [str(t) for t in raw_tools] if raw_tools else []

    model = str(meta.get("model", "")) if meta.get("model") is not None else ""

    return AgentSpec(
        description=str(description),
        mode=mode,
        tools=tools,
        model=model,
        system_prompt=system_prompt,
    )
