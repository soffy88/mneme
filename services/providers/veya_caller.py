"""本机 Veya gateway 的 OpenAI-compatible 文本/视觉 caller。

Veya gateway 由宿主机常驻进程提供，容器内通过
``http://host.docker.internal:8791/v1`` 访问。文本和视觉使用不同模型，
但共用同一个 ``/chat/completions`` 协议。
"""

from __future__ import annotations

import json
import os
from typing import Any

from obase.provider_timeout import provider_httpx_timeout


def _base_url() -> str:
    return (
        os.environ.get("VEYA_BASE_URL")
        or "http://127.0.0.1:8791/v1"
    ).rstrip("/")


def _headers() -> dict[str, str]:
    key = os.environ.get("VEYA_API_KEY", "").strip()
    return {"Authorization": f"Bearer {key}"} if key else {}


def _usage(data: dict[str, Any]) -> dict[str, int]:
    usage = data.get("usage") or {}
    return {
        "input_tokens": int(usage.get("prompt_tokens", 0) or 0),
        "output_tokens": int(usage.get("completion_tokens", 0) or 0),
    }


def _extract_json(text: str) -> Any:
    """Parse JSON responses while tolerating a fenced code block."""
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    return json.loads(stripped)


class VeyaTextCaller:
    """Veya text model caller implementing Mneme's LLM protocol."""

    def __init__(self, model: str | None = None) -> None:
        self.base_url = _base_url()
        self.model = model or os.environ.get("VEYA_MODEL", "veya1.2-128K")

    async def __call__(
        self,
        *,
        messages: list[dict[str, Any]],
        max_tokens: int = 1000,
        tools: list[dict[str, Any]] | None = None,
        response_format: str | None = None,
        system: str | None = None,
        enable_thinking: bool | None = None,
    ) -> dict[str, Any]:
        import httpx

        api_messages = list(messages)
        if system:
            api_messages.insert(0, {"role": "system", "content": system})
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": api_messages,
            "max_tokens": max_tokens,
        }
        if tools:
            payload["tools"] = tools
        if response_format == "json":
            payload["response_format"] = {"type": "json_object"}
        if enable_thinking is not None:
            payload["enable_thinking"] = enable_thinking

        async with httpx.AsyncClient(timeout=provider_httpx_timeout()) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers=_headers(),
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
        content = data["choices"][0]["message"].get("content") or ""
        return {"content": content, "usage": _usage(data)}


class VeyaVLCaller:
    """Veya vision-language caller using an OpenAI image_url content block."""

    def __init__(self, model: str | None = None) -> None:
        self.base_url = _base_url()
        self.model = model or os.environ.get("VEYA_VL_MODEL", "veya1.2-vl")

    async def __call__(
        self, *, prompt: str, image_b64: str, response_format: str = "text"
    ) -> dict[str, Any]:
        import httpx

        image_url = (
            image_b64
            if image_b64.startswith("data:")
            else f"data:image/jpeg;base64,{image_b64}"
        )
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": image_url}},
                    ],
                }
            ],
            "max_tokens": 2000,
        }
        async with httpx.AsyncClient(timeout=provider_httpx_timeout()) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers=_headers(),
                json=payload,
            )
            response.raise_for_status()
            data = response.json()

        raw_text = data["choices"][0]["message"].get("content") or ""
        content: Any = raw_text
        if response_format == "json":
            try:
                content = _extract_json(raw_text)
            except (TypeError, json.JSONDecodeError):
                content = raw_text
        return {
            "content": content,
            "raw_text": raw_text,
            "usage": _usage(data),
        }
