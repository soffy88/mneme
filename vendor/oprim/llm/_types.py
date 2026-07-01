from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any

@dataclass
class LLMResponse:
    text: str
    tool_calls: list[dict] = field(default_factory=list)
    stop_reason: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    raw: dict = field(default_factory=dict)
    model: str = ""

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

@dataclass
class StreamDelta:
    type: str
    text: str = ''
    tool_name: str = ''
    tool_id: str = ''
    tool_input: dict = field(default_factory=dict)
    input_tokens: int = 0
    output_tokens: int = 0
    stop_reason: str = ''
    thinking: str = ''

@dataclass
class EmbedResult:
    vector: list[float]
    model: str
    token_count: int

@dataclass
class ConversationSnapshot:
    snapshot_id: str
    store_key: str
    revision: str
    session_id: str = ""
    message_count: int = 0
    created_at: float = 0.0
    messages: list[dict] = field(default_factory=list)

@dataclass
class ThinkingResult:
    thinking: str
    text: str = ""
    has_thinking: bool = False
    thinking_blocks: list[str] = field(default_factory=list)
    text_blocks: list[str] = field(default_factory=list)

@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str
    rank: int = 0

@dataclass
class HttpResponse:
    status_code: int
    text: str
    headers: dict[str, str]
    url: str

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300

    def json(self) -> Any:
        import json
        try:
            return json.loads(self.text)
        except Exception as e:
            raise RuntimeError(f"response is not valid JSON: {e}")
