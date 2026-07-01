"""ProviderRegistry register for qwen3_dashscope (LLM + embedding via DashScope)."""
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

        model_id = model or "qwen-plus"
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
                    raise LLMRateLimitError(f"DashScope rate limit: {resp.message}")
                else:
                    raise LLMError(f"DashScope error {resp.status_code}: {resp.message}")
            except (LLMError, LLMRateLimitError):
                raise
            except Exception as e:
                last_err = e
                if attempt < 2:
                    olog.warning("dashscope llm retry", attempt=attempt, error=str(e))
                    time.sleep(2**attempt)
        raise LLMError(f"qwen3_dashscope failed after 3 retries: {last_err}") from last_err

    return caller


def register(*, replace: bool = False) -> None:
    """Register qwen3_dashscope LLM + embedding into ProviderRegistry."""
    from obase import ProviderRegistry
    from oprim.embedding.qwen3_dashscope import Qwen3DashscopeEmbedder

    ProviderRegistry.register("llm", "qwen3_dashscope", _make_llm_caller(), replace=replace)
    embedder = Qwen3DashscopeEmbedder()
    ProviderRegistry.register("embedding", "qwen3_dashscope", embedder.embed, replace=replace)
