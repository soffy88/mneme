"""Shared type definitions for CC supplement elements (P-NEW1..8, K-NEW1)."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class SkillRef:
    """Reference to a registered skill, with parsed command args."""

    name: str
    args: list[str] = field(default_factory=list)
    raw_input: str = ""


@dataclass
class PluginManifest:
    """Parsed plugin.json manifest."""

    name: str
    version: str
    skills: list[dict[str, Any]] = field(default_factory=list)
    subagents: list[dict[str, Any]] = field(default_factory=list)
    commands: list[dict[str, Any]] = field(default_factory=list)
    hooks: list[dict[str, Any]] = field(default_factory=list)
    mcp_defs: list[dict[str, Any]] = field(default_factory=list)
    description: str = ""


@dataclass
class PluginSpec:
    """Validated, install-ready plugin specification."""

    name: str
    version: str
    manifest: PluginManifest
    source_path: Path
    validation_errors: list[str] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return len(self.validation_errors) == 0


@dataclass
class PluginRegistry:
    """Read-only snapshot of installed plugins (for conflict checking)."""

    plugins: dict[str, PluginSpec] = field(default_factory=dict)
    command_names: set[str] = field(default_factory=set)
    skill_names: set[str] = field(default_factory=set)


@dataclass
class RunState:
    """Serializable runtime state for checkpointing."""

    session_id: str
    step: int = 0
    data: dict[str, Any] = field(default_factory=dict)
    completed_steps: list[str] = field(default_factory=list)


@dataclass
class CheckpointData:
    """Serialized checkpoint (pure data, no IO)."""

    session_id: str
    timestamp: str
    version: str = "1"
    payload: dict[str, Any] = field(default_factory=dict)
