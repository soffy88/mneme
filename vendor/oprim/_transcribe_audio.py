"""P-3: transcribe_audio — audio transcription via faster-whisper or DashScope Paraformer.

backend="local":
    Uses faster-whisper (CPU int8). Model is loaded from model_path — the path
    must exist. Model is NOT downloaded automatically; pre-download with:
        pip install faster-whisper
        python -c "from faster_whisper import download_model; download_model('base', cache_dir='/models/whisper')"

backend="dashscope":
    Uses DashScope Paraformer ASR API.
    IMPORTANT: DashScope Paraformer requires a publicly accessible audio URL.
    Local file paths cannot be submitted directly. Upload the audio file to object
    storage (e.g. OSS / S3) and pass the returned public URL as audio_path value,
    or use a file:// URI only if the DashScope service can reach the host.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from oprim._media_types import TranscriptResult


async def transcribe_audio(
    *,
    audio_path: Path,
    backend: str = "local",
    model_size: str = "base",
    language: str = "zh",
    model_path: str = "/models/whisper",
) -> TranscriptResult:
    """Transcribe audio to text.

    Args:
        audio_path: Path to the audio file (mp3 / wav / m4a).
        backend: "local" (faster-whisper, CPU int8) or "dashscope" (Paraformer API).
        model_size: Model size for faster-whisper ("tiny", "base", "small", etc.).
        language: BCP-47 language tag ("zh", "en", etc.).
        model_path: Directory containing the faster-whisper model weights.
                    Ignored for dashscope. Must exist — model is not downloaded automatically.

    Returns:
        TranscriptResult with text, segments, language, and duration.

    Raises:
        FileNotFoundError: audio_path does not exist.
        ValueError: backend is not "local" or "dashscope".
        RuntimeError: faster-whisper not installed (local) or model_path missing (local).
    """
    audio_path = Path(audio_path)
    if not audio_path.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    if backend == "local":
        return await _transcribe_local(
            audio_path, model_size=model_size, language=language, model_path=model_path
        )
    elif backend == "dashscope":
        return await _transcribe_dashscope(audio_path, language=language)
    else:
        raise ValueError(f"Unknown backend: {backend!r}. Choose 'local' or 'dashscope'.")


# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------

async def _transcribe_local(
    audio_path: Path,
    *,
    model_size: str,
    language: str,
    model_path: str,
) -> TranscriptResult:
    try:
        from faster_whisper import WhisperModel  # type: ignore[import]
    except ImportError:
        raise RuntimeError(
            "faster-whisper is not installed. Install with: pip install faster-whisper"
        )

    mp = Path(model_path)
    if not mp.exists():
        raise RuntimeError(
            f"Whisper model path does not exist: {model_path}. "
            "Download the model first (see module docstring)."
        )

    loop = asyncio.get_event_loop()

    def _run() -> tuple[str, list[dict], str, float]:
        model = WhisperModel(str(mp), device="cpu", compute_type="int8")
        segments_gen, info = model.transcribe(str(audio_path), language=language)
        segments: list[dict] = []
        parts: list[str] = []
        for seg in segments_gen:
            segments.append({"start": seg.start, "end": seg.end, "text": seg.text})
            parts.append(seg.text)
        return "".join(parts), segments, info.language, info.duration

    text, segments, lang, duration = await loop.run_in_executor(None, _run)
    return TranscriptResult(text=text, segments=segments, language=lang, duration=duration)


async def _transcribe_dashscope(audio_path: Path, *, language: str) -> TranscriptResult:
    """Call DashScope Paraformer ASR.

    NOTE: Paraformer requires a publicly accessible URL.
    See module-level docstring for upload instructions.
    """
    import os

    try:
        import dashscope  # type: ignore[import]
        from dashscope.audio.asr import Recognition  # type: ignore[import]
    except ImportError:
        raise RuntimeError(
            "dashscope is not installed. Install with: pip install dashscope"
        )

    api_key = os.environ.get("DASHSCOPE_API_KEY", "")
    dashscope.api_key = api_key

    # The path is expected to be a publicly accessible URL for Paraformer
    file_url = str(audio_path)

    loop = asyncio.get_event_loop()

    def _call() -> dict:
        response = Recognition.call(
            model="paraformer-realtime-v2",
            file_urls=[file_url],
            language_hints=[language],
        )
        return response

    response = await loop.run_in_executor(None, _call)

    output = response.output if hasattr(response, "output") else {}
    sentences = output.get("sentence", []) if isinstance(output, dict) else []

    segments = [
        {
            "start": s.get("begin_time", 0) / 1000.0,
            "end": s.get("end_time", 0) / 1000.0,
            "text": s.get("text", ""),
        }
        for s in sentences
    ]
    full_text = "".join(s["text"] for s in segments)
    duration = segments[-1]["end"] if segments else 0.0

    return TranscriptResult(
        text=full_text,
        segments=segments,
        language=language,
        duration=duration,
    )
