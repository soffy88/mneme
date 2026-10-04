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


# 网关会用 **HTTP 200** 把上游故障当正文返回。2026-10-03 实测：
#   {"content": "gpt-5.6-luna 兜底失败"}
#   {"content": "opencode-go rejected the request (HTTP 429): ... Go usage limit exceeded"}
# 所以「HTTP 没报错」**不等于**成功。这是回退逻辑能成立的前提。
GATEWAY_ERROR_MARKERS = (
    "兜底失败",
    "rejected the request",
    "usage limit",
    "no api-key",
    "rate_limit",
    "insufficient_quota",
    "service unavailable",
)


def looks_like_gateway_error(text: str | None) -> bool:
    low = (text or "").lower()
    return any(m in low for m in GATEWAY_ERROR_MARKERS)


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
    """Veya text model caller implementing Mneme's LLM protocol.

    **`VEYA_MODEL` 可以是逗号分隔的名单**，按顺序回退（2026-10-03 加）。

    为什么要有名单：实测可用模型**在会话中途就会变** —— `veya1.2` 在跑完 100 词
    真实试跑后开始返回「兜底失败」，只剩 `veya-deepseek-v4-flash-nv` 能回（且要
    68~90s）。把可用性押在单个名字上，等于把线上生成押在一个会漂移的配额上。

    回退的判定**必须看返回内容**：网关的故障是 HTTP 200 + 正文错误串，只判
    异常/状态码的话每个模型都会「成功」，回退永远不触发。
    """

    def __init__(self, model: str | None = None) -> None:
        self.base_url = _base_url()
        raw = model or os.environ.get("VEYA_MODEL", "veya1.2-128K")
        self.models: list[str] = [m.strip() for m in str(raw).split(",") if m.strip()]
        if not self.models:
            self.models = ["veya1.2-128K"]
        # 单模型时保持原字段名语义（别处会读 caller.model 记审计）
        self.model = self.models[0]
        self.last_good_model: str | None = None

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
        extras: dict[str, Any] = {}
        if tools:
            extras["tools"] = tools
        if response_format == "json":
            extras["response_format"] = {"type": "json_object"}
        if enable_thinking is not None:
            extras["enable_thinking"] = enable_thinking

        attempts: list[str] = []
        async with httpx.AsyncClient(timeout=provider_httpx_timeout()) as client:
            for candidate in self.models:
                payload: dict[str, Any] = {
                    "model": candidate,
                    "messages": api_messages,
                    "max_tokens": max_tokens,
                    **extras,
                }
                try:
                    response = await client.post(
                        f"{self.base_url}/chat/completions",
                        headers=_headers(),
                        json=payload,
                    )
                    response.raise_for_status()
                    data = response.json()
                    content = data["choices"][0]["message"].get("content") or ""
                except Exception as exc:  # noqa: BLE001 — 换下一个模型试
                    attempts.append(f"{candidate}: {type(exc).__name__}")
                    continue
                if looks_like_gateway_error(content):
                    # HTTP 200 但正文是上游错误串 —— 换一个模型，这不算成功
                    attempts.append(f"{candidate}: gateway_error_payload")
                    continue
                self.last_good_model = candidate
                self.model = candidate
                return {"content": content, "usage": _usage(data)}

        # 名单全废：抛一个把每个模型的失败原因都带上的异常，便于一眼定位
        raise RuntimeError(
            "all VEYA_MODEL candidates failed: " + " | ".join(attempts)
        )


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
