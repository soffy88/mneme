"""ProviderRegistry register for qwen3 (LLM via DashScope, qwen3-max default)."""
from __future__ import annotations


def _make_llm_caller() -> object:
    from oprim._config import cfg
    from oprim._logging import log as olog
    from oprim.errors import LLMError, LLMRateLimitError

    import time

    def caller(
        messages: list[dict],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        **_: object,
    ) -> object:
        import dashscope
        from dashscope import Generation

        api_key = cfg.get("DASHSCOPE_API_KEY")
        if api_key:
            dashscope.api_key = str(api_key)

        model_id = model or "qwen3-max"
        last_err: Exception | None = None
        for attempt in range(3):
            try:
                resp = Generation.call(
                    model=model_id,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    result_format="message",
                )
                if resp.status_code == 200:
                    return resp
                elif resp.status_code == 429:
                    raise LLMRateLimitError(f"DashScope rate limit (qwen3): {resp.message}")
                else:
                    raise LLMError(f"DashScope error {resp.status_code}: {resp.message}")
            except (LLMError, LLMRateLimitError):
                raise
            except Exception as e:
                last_err = e
                if attempt < 2:
                    olog.warning("qwen3 llm retry", attempt=attempt, error=str(e))
                    time.sleep(2**attempt)
        raise LLMError(f"qwen3 failed after 3 retries: {last_err}") from last_err

    return caller


def register(*, replace: bool = False) -> None:
    """Register qwen3 LLM into ProviderRegistry."""
    from obase import ProviderRegistry

    ProviderRegistry.register("llm", "qwen3", _make_llm_caller(), replace=replace)
