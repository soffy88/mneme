"""oprim._hevi_types — Shared types for hevi Phase 10/11 elements."""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel


class VideoQuality(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    ULTRA = "ultra"


class ProviderCapability(str, Enum):
    TEXT_TO_VIDEO = "t2v"
    IMAGE_TO_VIDEO = "i2v"
    VIDEO_TO_VIDEO = "v2v"
    TEXT_TO_IMAGE = "t2i"
    IMAGE_TO_IMAGE = "i2i"
    AUDIO = "audio"
    SCRIPT = "script"


class Subject(BaseModel):
    """A persistent creative subject (character, prop, location, etc.)."""

    subject_id: str
    name: str
    description: str = ""
    subject_type: str = "character"
    reference_images: list[str] = []
    metadata: dict[str, Any] = {}
    tags: list[str] = []
    version: int = 1


class CanvasNode(BaseModel):
    """A node in a creative workflow canvas."""

    node_id: str
    node_type: str
    label: str = ""
    config: dict[str, Any] = {}
    position: dict[str, float] = {}


class CanvasEdge(BaseModel):
    """A directed edge connecting two canvas nodes."""

    edge_id: str
    from_node_id: str
    to_node_id: str
    from_type: str = ""
    to_type: str = ""
    label: str = ""
