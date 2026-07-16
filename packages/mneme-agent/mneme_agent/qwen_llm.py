"""qwen_llm —— 独立 qwen tool-calling llm_caller（FC-7：仅供 tutor-loop 循环驱动）。

零 DB、无 services import。经 DashScope OpenAI 兼容端点做 function-calling，把 oservi
AgenticLoop 的 Anthropic 风格 content-blocks（tool_use / tool_result）↔ OpenAI
（tool_calls / role=tool）互转，返回引擎期望的 {content:[tool_use|text], stop_reason, usage}。

verifier 仍注入伪 LLMCaller（W2b 边界，不在此）。base_url/key/model 全走环境变量。
"""

from __future__ import annotations

import json
import os
from typing import Any


def _base_url() -> str:
    return (os.environ.get("QWEN_BASE_URL") or "").rstrip("/") or (
        "https://dashscope.aliyuncs.com/compatible-mode/v1"
    )


def _to_openai_tools(tools: list[dict] | None) -> list[dict]:
    """loop 传的 tools 是 Anthropic 风格 {name, description, input_schema} → OpenAI function。"""
    out = []
    for t in tools or []:
        schema = (
            t.get("input_schema")
            or t.get("parameters")
            or {"type": "object", "properties": {}}
        )
        out.append(
            {
                "type": "function",
                "function": {
                    "name": t.get("name"),
                    "description": t.get("description", ""),
                    "parameters": schema,
                },
            }
        )
    return out


def _to_openai_messages(messages: list[dict]) -> list[dict]:
    """oservi content-blocks → OpenAI chat messages（含 tool_calls / role=tool）。"""
    out: list[dict] = []
    for m in messages:
        role = m.get("role")
        content = m.get("content")
        if isinstance(content, str):
            out.append({"role": role, "content": content})
            continue
        if role == "assistant":
            texts, tool_calls = [], []
            for b in content or []:
                if b.get("type") == "text":
                    texts.append(b.get("text", ""))
                elif b.get("type") == "tool_use":
                    tool_calls.append(
                        {
                            "id": b.get("id"),
                            "type": "function",
                            "function": {
                                "name": b.get("name"),
                                "arguments": json.dumps(
                                    b.get("input", {}), ensure_ascii=False
                                ),
                            },
                        }
                    )
            msg: dict[str, Any] = {
                "role": "assistant",
                "content": ("\n".join(texts) or None),
            }
            if tool_calls:
                msg["tool_calls"] = tool_calls
            out.append(msg)
        elif role == "user":
            for b in content or []:
                if b.get("type") == "tool_result":
                    out.append(
                        {
                            "role": "tool",
                            "tool_call_id": b.get("tool_use_id"),
                            "content": str(b.get("content", "")),
                        }
                    )
                elif b.get("type") == "text":
                    out.append({"role": "user", "content": b.get("text", "")})
        else:
            out.append({"role": role or "user", "content": str(content)})
    return out


class QwenLoopCaller:
    """oservi AgenticLoop 的 llm_caller：__call__(messages, tools, ...) → Anthropic 风格 dict。"""

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        self.api_key = api_key or os.environ["DASHSCOPE_API_KEY"]
        self.model = model or os.environ.get("QWEN_MODEL", "qwen-plus")
        self.base_url = _base_url()

    async def __call__(
        self,
        *,
        messages,
        tools=None,
        max_tokens: int = 2048,
        thinking_budget=None,
        system: str | None = None,
    ) -> dict:
        import httpx

        api_messages = list(messages)
        if system:
            api_messages.insert(0, {"role": "system", "content": system})
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": _to_openai_messages(api_messages),
            "max_tokens": max_tokens,
        }
        oai_tools = _to_openai_tools(tools)
        if oai_tools:
            payload["tools"] = oai_tools

        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()

        msg = data["choices"][0]["message"]
        usage = data.get("usage", {})
        usage_out = {
            "input_tokens": usage.get("prompt_tokens", 0),
            "output_tokens": usage.get("completion_tokens", 0),
        }

        tool_calls = msg.get("tool_calls") or []
        if tool_calls:
            content = []
            for tc in tool_calls:
                fn = tc.get("function", {})
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                content.append(
                    {
                        "type": "tool_use",
                        "id": tc.get("id", "tc"),
                        "name": fn.get("name"),
                        "input": args,
                    }
                )
            return {"content": content, "stop_reason": "tool_use", "usage": usage_out}
        return {
            "content": [{"type": "text", "text": msg.get("content") or ""}],
            "stop_reason": "end_turn",
            "usage": usage_out,
        }
