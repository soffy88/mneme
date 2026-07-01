"""Shared types for shot rendering elements."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ShotResult:
    output_path: Path
    shot_type: str          # "generative" | "code_render"
    duration_s: float
    metadata: dict
    is_valid: bool = True
    validation_violations: list[str] = field(default_factory=list)
