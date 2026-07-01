"""P-3: text_to_speech — single-call cloud TTS via ProviderRegistry.

Not the same as vibevoice_synthesize (which is local, multi-speaker).
This function targets cloud, single-channel TTS for language learning prompts.
"""

from __future__ import annotations

import base64


async def text_to_speech(
    *,
    text: str,
    language: str = "en",
    voice: str = "default",
    provider: str = "default",
) -> str:
    """Synthesise text to speech; return base-64 encoded audio.

    Uses the "tts" provider in ProviderRegistry. Distinct from vibevoice_synthesize
    (local multi-speaker); this function is for cloud, single-channel synthesis used
    in language practice prompts.

    Args:
        text: Text to synthesise.
        language: Target language ("en" or "zh").
        voice: Voice name supported by the provider ("default" is provider-specific).
        provider: Provider name registered under category "tts".

    Returns:
        Base-64 encoded audio string.

    Raises:
        ValueError: text is empty.
        RuntimeError: provider not registered.
    """
    if not text:
        raise ValueError("text must not be empty")

    from obase.provider_registry import ProviderRegistry

    caller = ProviderRegistry.get().generic("tts", provider)
    result = await caller(text=text, language=language, voice=voice)

    if isinstance(result, str):
        _validate_base64(result)
        return result

    audio = result.get("audio_b64", result.get("audio", ""))
    _validate_base64(audio)
    return audio


def _validate_base64(value: str) -> None:
    """Raise ValueError if value is not valid base-64 (best-effort)."""
    if not value:
        return
    try:
        base64.b64decode(value, validate=True)
    except Exception as exc:
        raise ValueError(f"Provider returned invalid base-64 audio: {exc}") from exc
