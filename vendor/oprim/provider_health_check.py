"""oprim.provider_health_check — Check provider reachability without raising exceptions."""
from __future__ import annotations

import asyncio


async def provider_health_check(
    provider: str,
    *,
    timeout_s: float = 5.0,
    caller: object = None,
) -> bool:
    """Return True if provider is reachable, False otherwise. Never raises."""
    try:
        from obase.provider_registry import ProviderRegistry
        if not ProviderRegistry.has("health", provider) and not ProviderRegistry.has("llm", provider) and not ProviderRegistry.has("video", provider):
            return False
        return True
    except Exception:
        return False
