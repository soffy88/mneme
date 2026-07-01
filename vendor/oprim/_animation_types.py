"""Shared types and schema constants for CC animation elements."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class HtmlValidationResult:
    is_safe: bool
    violations: list[str]
    sanitized: str | None  # dangerous content removed; None when html is safe


@dataclass
class AnimationResult:
    html: str
    is_valid: bool
    validation_violations: list[str]
    entity_meta: dict  # generation metadata (no DB fields)


@dataclass
class AnimationInput:
    template: str       # prompt template with {placeholder} vars
    variables: dict     # values to fill the template
    domain_prompt: str  # domain-specific generation instruction


# ---------------------------------------------------------------------------
# Reference schema constants — Layer4 can override (table/column names vary)
# These are read-only defaults; the main library does NOT create tables.
# ---------------------------------------------------------------------------

DEFAULT_ANIMATION_SCHEMA = {
    "table": "animations",
    "columns": {"id", "html", "entity_id", "domain", "status", "created_at"},
}

DEFAULT_ANIM_TEMPLATE_SCHEMA = {
    "table": "anim_templates",
    "columns": {"id", "domain", "prompt", "vars"},
}

DEFAULT_ANIM_JOB_SCHEMA = {
    "table": "anim_jobs",
    "columns": {"id", "entity_ids", "status"},
}
