"""Auto-split from hicode whl. Verify before use."""

from __future__ import annotations
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any
from ._exceptions import OprimError
from ._protocols import EmbedCaller, StreamingLLMCaller

class LLMOprimError(OprimError):
    """LLM 调用失败（含 provider 错误、预算超出、格式错误）."""

class BudgetExceededError(LLMOprimError):
    """Token 预算超出."""

@dataclass
class LLMResponse:
    """规范化的 LLM 响应结构。"""
    text: str
    tool_calls: list[dict]
    stop_reason: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    raw: dict = field(default_factory=dict)

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

@dataclass
class StreamDelta:
    """流式响应的单个 delta。"""
    type: str
    text: str = ''
    tool_name: str = ''
    tool_id: str = ''
    tool_input: dict = field(default_factory=dict)
    input_tokens: int = 0
    output_tokens: int = 0
    stop_reason: str = ''

@dataclass
class EmbedResult:
    """嵌入结果。"""
    vector: list[float]
    model: str
    token_count: int

async def llm_complete(
    messages: list[dict],
    *,
    caller: Any,  # LLMCaller Protocol（来自 _protocols 或 obase.ProviderRegistry）
    tools: list[dict] | None = None,
    max_tokens: int = 4096,
    system: str | None = None,
    budget_tokens: int | None = None,
    model: str = "claude-sonnet-4-6",
    pricing: dict[str, float] | None = None,
) -> LLMResponse:
    """单次 LLM 调用，含消息校验 + token 截断 + 错误标准化 + usage 提取。

    M1 裁决：这不是 caller 的 alias。原子价值：
    1. 消息格式校验（role 合法性 / content 存在性）
    2. token 预算检查（budget_tokens 超出时抛 BudgetExceededError）
    3. 统一调用 caller（屏蔽 provider 差异）
    4. 错误标准化（provider 异常 → LLMOprimError）
    5. usage 字段提取（input_tokens / output_tokens / cost_usd）

    Args:
        messages: 消息列表（role + content）。
        caller: LLMCaller Protocol 实例（由调用方注入）。
        tools: 工具 schema 列表（可选）。
        max_tokens: 最大输出 token 数，默认 4096。
        system: system prompt（可选，部分 provider 作为独立参数）。
        budget_tokens: 输入 token 预算；估算超出时抛 BudgetExceededError。
        model: 模型名（用于成本估算）。
        pricing: 自定义价格 {"in": float, "out": float}（USD/token）。

    Returns:
        LLMResponse（含 text / tool_calls / stop_reason / tokens / cost）。

    Raises:
        LLMOprimError: 消息格式错误或 provider 调用失败。
        BudgetExceededError: 输入 token 超出 budget_tokens。

    Example:
        >>> resp = await llm_complete(
        ...     [{"role": "user", "content": "hello"}],
        ...     caller=my_caller,
        ... )
        >>> resp.text
        'Hello! How can I help you?'
        >>> resp.input_tokens
        12
    """
    # 1. 消息校验
    errors = _validate_messages(messages)
    if errors:
        raise LLMOprimError(f"invalid messages: {'; '.join(errors)}")

    # 2. token 预算估算（粗估，精确版由 obase.TokenCounter 提供）
    if budget_tokens is not None:
        total_chars = sum(
            len(json.dumps(m, ensure_ascii=False)) for m in messages
        )
        estimated = total_chars // 4
        if estimated > budget_tokens:
            raise BudgetExceededError(
                f"estimated input tokens ~{estimated} exceeds budget {budget_tokens}"
            )

    # 3. 调用 caller（屏蔽 provider 差异）
    try:
        kwargs: dict[str, Any] = dict(
            messages=messages,
            tools=tools,
            max_tokens=max_tokens,
        )
        if system is not None:
            kwargs["system"] = system
        raw = await caller(**kwargs)
    except (LLMOprimError, BudgetExceededError):
        raise  # pragma: no cover
    except Exception as e:
        raise LLMOprimError("LLM call failed", cause=e)

    # 4. 响应格式校验
    if not isinstance(raw, dict):
        raise LLMOprimError(f"caller returned non-dict: {type(raw).__name__}")

    # 5. usage 提取 + 成本计算
    usage = _extract_usage(raw)
    in_tok = usage["input_tokens"]
    out_tok = usage["output_tokens"]
    p = pricing or {"in": 3e-6, "out": 15e-6}
    cost = in_tok * p["in"] + out_tok * p["out"]

    return LLMResponse(
        text=_extract_text(raw),
        tool_calls=_extract_tool_calls(raw),
        stop_reason=raw.get("stop_reason", raw.get("finish_reason", "end_turn")),
        input_tokens=in_tok,
        output_tokens=out_tok,
        cost_usd=cost,
        raw=raw,
    )
