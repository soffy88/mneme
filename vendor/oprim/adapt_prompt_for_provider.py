"""oprim.adapt_prompt_for_provider — Adapt a prompt string for a specific LLM/VLM provider."""
from __future__ import annotations

_PROVIDER_RULES: dict[str, dict[str, str]] = {
    "wan22": {"prefix": "电影级画质，", "suffix": "，高清流畅"},
    "ltx2":  {"prefix": "", "suffix": ", cinematic, 4K"},
    "flux":  {"prefix": "", "suffix": ", masterpiece, best quality"},
}


async def adapt_prompt_for_provider(
    prompt: str,
    *,
    provider: str,
    negative_prompt: str = "",
    caller: object = None,
) -> dict:
    """Return adapted prompt dict for the given provider.

    Returns:
        {"prompt": str, "negative_prompt": str, "provider": str}
    """
    rules = _PROVIDER_RULES.get(provider, {})
    adapted = rules.get("prefix", "") + prompt + rules.get("suffix", "")
    return {"prompt": adapted, "negative_prompt": negative_prompt, "provider": provider}
