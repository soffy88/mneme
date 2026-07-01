"""P-1: speech_to_text — single-call ASR via ProviderRegistry.

No LLM involved; purely delegates to the registered ASR provider.
"""

from __future__ import annotations


async def speech_to_text(
    *,
    audio_b64: str,
    language: str = "zh",
    provider: str = "default",
) -> str:
    """Transcribe audio to text via the registered ASR provider.

    Args:
        audio_b64: Base-64 encoded audio data.
        language: BCP-47 language tag; "zh" or "en".
        provider: Name of the ASR provider registered in ProviderRegistry.
                  Defaults to "default".

    Returns:
        Recognised text string.

    Raises:
        ValueError: audio_b64 is empty.
        RuntimeError: provider not registered.
    """
    if not audio_b64:
        raise ValueError("audio_b64 must not be empty")

    from obase.provider_registry import ProviderRegistry

    caller = ProviderRegistry.get().generic("asr", provider)
    result = await caller(audio_b64=audio_b64, language=language)

    if isinstance(result, str):
        return result
    return str(result.get("text", ""))
