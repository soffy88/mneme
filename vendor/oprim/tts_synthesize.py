"""oprim.tts_synthesize — Text-to-speech synthesis via provider injection.

Example:
    >>> import asyncio
    >>> from pathlib import Path
    >>> from oprim.tts_synthesize import tts_synthesize
    >>> result = asyncio.run(tts_synthesize(
    ...     provider="edge_tts", text="Hello world", voice="zh-CN-XiaoxiaoNeural",
    ...     output_path=Path("speech.mp3"),
    ... ))

Raises:
    TTSError: Synthesis failed.
"""

from __future__ import annotations

from pathlib import Path

from obase import ProviderRegistry
from obase.exceptions import ProviderNotFoundError


class TTSError(Exception):
    """TTS synthesis failed."""


async def tts_synthesize(
    *,
    provider: str,
    text: str,
    voice: str,
    output_path: Path,
    rate: str = "+0%",
    pitch: str = "+0Hz",
    timeout_s: float = 60.0,
) -> Path:
    """Synthesize speech from text using a TTS provider.

    Args:
        provider: TTS provider name in ProviderRegistry (category='tts').
        text: Text to synthesize.
        voice: Voice identifier (provider-specific).
        output_path: Destination audio file.
        rate: Speech rate adjustment (e.g. "+20%", "-10%").
        pitch: Pitch adjustment (e.g. "+5Hz").
        timeout_s: Timeout in seconds.

    Returns:
        The output_path on success.

    Raises:
        TTSError: On validation failure or provider error.

    Example:
        >>> await tts_synthesize(
        ...     provider="edge_tts", text="Hi", voice="en-US-AriaNeural",
        ...     output_path=Path("out.mp3"),
        ... )
    """
    if not text:
        raise TTSError("text must not be empty")

    try:
        tts_fn = ProviderRegistry.get().generic("tts", provider)
    except ProviderNotFoundError as exc:
        raise TTSError(f"TTS provider not found: {provider!r}") from exc

    try:
        await tts_fn(
            text=text,
            voice=voice,
            output_path=output_path,
            rate=rate,
            pitch=pitch,
            timeout_s=timeout_s,
        )
    except Exception as exc:
        if isinstance(exc, TTSError):
            raise
        raise TTSError(f"TTS synthesis failed: {exc}") from exc

    if not output_path.exists():
        raise TTSError(f"Provider did not produce output: {output_path}")

    return output_path
