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


# ---------------------------------------------------------------------------
# 推理模型（2026-10-11 生产事故）
#
# Veya 宕机时回退链落到 InternAI ``Agents-A1``：它是推理模型，先把 max_tokens
# 花在 reasoning_content 上。实测 max_tokens=600 → content 为空、
# finish_reason=length；而且 ``enable_thinking=False`` /
# ``chat_template_kwargs.enable_thinking=False`` 均被端点**忽略**（照样 600 个
# token 全是思考）。**有效的是** ``thinking={"type": "disabled"}``：同一 prompt
# 0.6s、59 token、content 正常（2026-10-11 实测）。所以：
#   0. 推理模型默认发 ``thinking.disabled``（``MNEME_REASONING_THINKING_OFF=0`` 可关，
#      调用方显式 ``enable_thinking=True`` 时也不发）；
#   1. 仍给推理模型抬 max_tokens 下限——万一端点不认 thinking 开关，思考 + 回答
#      也要装得下；
#   2. 推理模型单次读超时更长（长生成常 >60s）；
#   3. 空 content（且无 tool_calls）一律算失败，换下一个候选/端点 ——
#      HTTP 200 + 空正文不是成功。
# ---------------------------------------------------------------------------

_DEFAULT_REASONING_MODELS = "Agents-A1"


def reasoning_models() -> frozenset[str]:
    """逗号分隔的推理模型名单（``MNEME_REASONING_MODELS``，大小写不敏感）。"""
    raw = os.environ.get("MNEME_REASONING_MODELS", _DEFAULT_REASONING_MODELS)
    return frozenset(m.strip().lower() for m in raw.split(",") if m.strip())


def is_reasoning_model(model: str | None) -> bool:
    return bool(model) and str(model).strip().lower() in reasoning_models()


def _bounded_env(name: str, default: float, low: float, high: float) -> float:
    try:
        value = float(os.environ.get(name, "") or default)
    except ValueError:
        return default
    return max(low, min(value, high))


def reasoning_thinking_off() -> bool:
    return os.environ.get("MNEME_REASONING_THINKING_OFF", "1").strip().lower() not in (
        "0", "false", "no", "off"
    )


def reasoning_min_tokens() -> int:
    """推理模型的 max_tokens 下限（默认 8192：实测 600/4000 仍可能全花在思考上）。"""
    return int(_bounded_env("MNEME_REASONING_MIN_TOKENS", 8192, 1024, 32768))


def reasoning_read_timeout_seconds() -> float:
    """推理模型单次 HTTP 读超时（默认 150s，上限 300s）。"""
    return _bounded_env("MNEME_REASONING_READ_TIMEOUT_SECONDS", 150.0, 30.0, 300.0)


class EmptyCompletionError(RuntimeError):
    """HTTP 200 但 content 为空（且无 tool_calls）——推理模型额度被思考吃光的典型形态。"""


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

    def _auth_headers(self) -> dict[str, str]:
        """鉴权头。**抽成方法**是为了让换端点的子类（`InternAiTextCaller`）能覆写，
        而不必把下面整套回退 + 内容校验逻辑复制一份。"""
        return _headers()

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
        async with httpx.AsyncClient(timeout=self._http_timeout(httpx)) as client:
            for candidate in self.models:
                reasoning = is_reasoning_model(candidate)
                payload: dict[str, Any] = {
                    "model": candidate,
                    "messages": api_messages,
                    # 推理模型：思考 + 回答都要装得下，否则 content 为空
                    "max_tokens": (
                        max(max_tokens, reasoning_min_tokens()) if reasoning else max_tokens
                    ),
                    **extras,
                }
                if reasoning and enable_thinking is not True and reasoning_thinking_off():
                    payload["thinking"] = {"type": "disabled"}
                # 每个模型名只试一次，失败就换下一个。**这里刻意不做重试**：
                # `services/providers/reliability.py` 已把所有传输类错误分类成
                # retryable（timeout / connect / 5xx / 429，见 _classify_exception）
                # 并带 max_retries=2 重投整条链。再叠一层只会让最坏耗时成倍相乘
                # —— 曾经把单个词的等待推到几十分钟（实测卡在第 95 词 4 分钟）。
                try:
                    response = await client.post(
                        f"{self.base_url}/chat/completions",
                        headers=self._auth_headers(),
                        json=payload,
                    )
                    response.raise_for_status()
                    data = response.json()
                    message = data["choices"][0]["message"]
                    content = message.get("content") or ""
                except Exception as exc:  # noqa: BLE001 — 换下一个模型试
                    attempts.append(f"{candidate}: {type(exc).__name__}")
                    continue
                if not str(content).strip() and not message.get("tool_calls"):
                    # HTTP 200 + 空正文不是成功（推理模型思考吃光额度时 finish=length）
                    finish = (data.get("choices") or [{}])[0].get("finish_reason")
                    attempts.append(f"{candidate}: empty_content(finish={finish})")
                    continue
                if looks_like_gateway_error(content):
                    # HTTP 200 但正文是上游错误串 —— 换一个模型，这不算成功
                    attempts.append(f"{candidate}: gateway_error_payload")
                    continue
                self.last_good_model = candidate
                self.model = candidate
                return {
                    "content": content,
                    "usage": _usage(data),
                    "finish_reason": (data.get("choices") or [{}])[0].get("finish_reason"),
                }

        # 名单全废：抛一个把每个模型的失败原因都带上的异常，便于一眼定位
        detail = "all VEYA_MODEL candidates failed: " + " | ".join(attempts)
        if attempts and all("empty_content" in a for a in attempts):
            raise EmptyCompletionError(detail)
        raise RuntimeError(detail)

    @property
    def has_reasoning_model(self) -> bool:
        return any(is_reasoning_model(m) for m in self.models)

    def _http_timeout(self, httpx: Any) -> Any:
        """名单里有推理模型就用更长的读超时；否则沿用共享的有界策略。"""
        if not self.has_reasoning_model:
            return provider_httpx_timeout()
        read = reasoning_read_timeout_seconds()
        connect = float(os.environ.get("MNEME_PROVIDER_CONNECT_TIMEOUT_SECONDS", "") or 5.0)
        connect = max(1.0, min(connect, 15.0))
        return httpx.Timeout(connect=connect, read=read, write=read, pool=connect)


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
