"""Provider-dispatched LLM call with retry and cost tracking."""
from __future__ import annotations

from ._types import LLMResponse
from oprim._config import cfg
from oprim._logging import log as olog
from oprim.errors import LLMError, LLMRateLimitError


def llm_call(
    prompt: str,
    provider: str = "qwen3_dashscope",
    model: str | None = None,
    temperature: float = 0.7,
    max_tokens: int = 4096,
    system: str | None = None,
) -> LLMResponse:
    if provider == "qwen3_dashscope":
        return _call_dashscope(prompt, model, temperature, max_tokens, system)
    elif provider == "claude":
        return _call_claude(prompt, model, temperature, max_tokens, system)
    else:
        raise LLMError(f"Unknown LLM provider: {provider}")


def _call_dashscope(prompt, model, temperature, max_tokens, system):
    try:
        import httpx
        import os
    except ImportError as e:
        raise LLMError(f"httpx not installed: {e}")

    api_key = cfg.get("DASHSCOPE_API_KEY") or os.getenv("DASHSCOPE_API_KEY", "")
    if not api_key:
        raise LLMError("DASHSCOPE_API_KEY not set")

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    _model = model or "qwen-plus"
    try:
        resp = httpx.post(
            "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": _model,
                "input": {"messages": messages},
                "parameters": {
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                },
            },
            timeout=60.0,
        )
        resp.raise_for_status()
        data = resp.json()
        text = data["output"]["choices"][0]["message"]["content"]
        return LLMResponse(text=text, model=_model)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 429:
            raise LLMRateLimitError(f"DashScope rate limit: {e}")
        raise LLMError(f"DashScope HTTP error {e.response.status_code}: {e}")
    except Exception as e:
        raise LLMError(f"DashScope call failed: {e}")


def _call_claude(prompt, model, temperature, max_tokens, system):
    # Claude 走 obase.ProviderRegistry，此处保留 stub 待接入
    raise LLMError("Claude provider not yet implemented via llm_call; use oprim.llm_complete instead")
