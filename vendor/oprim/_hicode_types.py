"""Shared types for hicode batch H-A pure-compute oprim elements."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

# ── Primitive aliases ─────────────────────────────────────────────────────────

StopReason = Literal["end_turn", "tool_use", "max_tokens", "stop_sequence", "unknown"]
RiskLevel = Literal["high", "medium", "low"]
Decision = Literal["allow", "ask", "deny"]

# ── Tool call / result ────────────────────────────────────────────────────────


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict[str, Any]


@dataclass
class ToolResult:
    call_id: str
    content: str
    is_error: bool = False


# ── Part & Message ────────────────────────────────────────────────────────────


@dataclass
class Part:
    """Single content block inside a Message."""

    type: str  # text / tool_call / tool_result / file / image / reasoning
    text: str | None = None
    tool_call: ToolCall | None = None
    tool_result: ToolResult | None = None
    path: Path | None = None
    mime: str | None = None
    data: str | None = None  # base64 for image parts
    pinned: bool = False


@dataclass
class PartDelta:
    """Streaming chunk for a single Part."""

    type: str
    index: int = 0
    text: str | None = None
    tool_call_id: str | None = None
    tool_name: str | None = None
    args_chunk: str | None = None


@dataclass
class Message:
    role: str  # user / assistant / system / tool
    parts: list[Part]
    pinned: bool = False


# ── Edit / Patch / Conflict ───────────────────────────────────────────────────


@dataclass
class Edit:
    old: str
    new: str


@dataclass
class Patch:
    old: str
    new: str
    idx: int  # edit index in the plan


@dataclass
class Conflict:
    idx_a: int
    idx_b: int


# ── File / Grep ───────────────────────────────────────────────────────────────


@dataclass
class Hit:
    path: str
    line_no: int
    col: int
    text: str


@dataclass
class FileEntry:
    path: Path
    mtime: float
    size: int = 0


@dataclass
class Entry:
    path: Path
    is_dir: bool
    children: list[Entry] = field(default_factory=list)


@dataclass
class Pattern:
    """gitignore-style pattern."""

    pattern: str
    negated: bool = False
    anchored: bool = False  # original starts with /
    dir_only: bool = False  # original ends with /


# ── Process / Shell ───────────────────────────────────────────────────────────


@dataclass
class SignalInfo:
    code: int
    is_signal: bool
    signal_no: int | None = None
    name: str | None = None
    description: str | None = None


# ── Todo ──────────────────────────────────────────────────────────────────────


@dataclass
class Todo:
    id: str
    content: str
    status: str  # pending / in_progress / completed / cancelled
    priority: str = "medium"  # high / medium / low


@dataclass
class TodoDelta:
    added: list[Todo]
    removed: list[Todo]
    status_changed: list[tuple[Todo, str]]  # (todo, old_status)


# ── Session ───────────────────────────────────────────────────────────────────


@dataclass
class Session:
    id: str
    title: str
    messages: list[Message]
    created_at: float
    model: str = ""
    agent: str = ""
    version: int = 1


@dataclass
class StateDelta:
    new_messages: list[Message]
    changed_fields: dict[str, Any]
    warning: str | None = None


@dataclass
class Window:
    to_compact: list[Message]
    to_keep: list[Message]


# ── Event / Share ─────────────────────────────────────────────────────────────


@dataclass
class Event:
    id: str
    type: str
    payload: dict[str, Any]
    timestamp: float


@dataclass
class Filter:
    type: str | None = None
    condition: dict[str, Any] | None = None


# ── Model / Agent ─────────────────────────────────────────────────────────────


@dataclass
class ModelSpec:
    id: str
    name: str
    provider: str
    context_length: int = 8192
    supports_tools: bool = False
    supports_vision: bool = False
    supports_reasoning: bool = False
    curated: bool = False
    cost_per_input_token: float = 0.0
    cost_per_output_token: float = 0.0


@dataclass
class Capabilities:
    tools: bool
    vision: bool
    reasoning: bool
    max_context: int


@dataclass
class TaskHint:
    needs_tools: bool = False
    needs_vision: bool = False
    needs_reasoning: bool = False
    min_context: int = 0


@dataclass
class AgentSpec:
    description: str
    mode: str  # primary / subagent / all
    tools: list[str]
    model: str
    system_prompt: str


@dataclass
class SkillSpec:
    name: str
    description: str
    body: str


# ── Permissions ───────────────────────────────────────────────────────────────


@dataclass
class BashRule:
    pattern: str
    action: Decision


@dataclass
class Rule:
    pattern: str
    action: Decision


@dataclass
class Persona:
    name: str
    mode: str = "build"  # build / plan / subagent
    allow: list[str] = field(default_factory=list)
    deny: list[str] = field(default_factory=list)
    bash_rules: list[BashRule] = field(default_factory=list)


@dataclass
class PermSet:
    tool_actions: dict[str, Decision] = field(default_factory=dict)
    bash_rules: list[BashRule] = field(default_factory=list)


# ── Tool ──────────────────────────────────────────────────────────────────────


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict[str, Any] = field(default_factory=dict)


# ── Subagent / MCP / Question ─────────────────────────────────────────────────


@dataclass
class SubagentResult:
    status: str  # success / error
    content: str
    error: str | None = None


@dataclass
class McpToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass
class Question:
    text: str
    options: list[str]
    header: str = ""


@dataclass
class Answer:
    option_idx: int | None = None
    text: str | None = None


# ── Git / File change ─────────────────────────────────────────────────────────


@dataclass
class GitStatus:
    modified: list[str]
    added: list[str]
    deleted: list[str]
    untracked: list[str]


@dataclass
class FileChange:
    path: str
    status: str
