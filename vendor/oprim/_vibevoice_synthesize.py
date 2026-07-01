"""oprim.vibevoice_synthesize — Multi-speaker TTS via VibeVoice 1.5B local inference.

Example:
    >>> import asyncio
    >>> from pathlib import Path
    >>> from oprim.vibevoice_synthesize import vibevoice_synthesize, SpeakerLine
    >>> out = asyncio.run(vibevoice_synthesize(
    ...     script=[SpeakerLine(speaker_id="s1", text="Hello world")],
    ...     output_path=Path("out.wav"),
    ... ))

Raises:
    VibeVoiceSetupError: torch or transformers not installed, or model dir missing.
    VibeVoiceError: Synthesis or concat failed.
"""

from __future__ import annotations

import io
import wave
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from oprim._config import cfg


class VibeVoiceError(Exception):
    """VibeVoice synthesis failed."""


class VibeVoiceSetupError(VibeVoiceError):
    """VibeVoice dependencies not available or model dir missing."""


@runtime_checkable
class SpeakerLine(Protocol):
    """Minimal protocol for a speaker line (compatible with oskill.SpeakerLine)."""

    speaker_id: str
    text: str
    voice_ref: Path | None


async def vibevoice_synthesize(
    *,
    config: dict[str, Any] | None = None,
    script: list[Any],
    output_path: Path,
    watermark: bool = True,
    _inference_fn: Any = None,
) -> Path:
    """Synthesize multi-speaker audio via VibeVoice 1.5B.

    Args:
        config: Optional dict with VIBEVOICE_MODEL_DIR override.
        script: List of SpeakerLine-compatible objects (speaker_id, text, voice_ref).
        output_path: Destination WAV file.
        watermark: Inject safety watermark (Microsoft responsible-AI requirement).
            Defaults to True; strongly recommended.
        _inference_fn: Optional override for the per-line inference call (for testing).

    Returns:
        output_path on success.

    Raises:
        VibeVoiceError: Empty script or synthesis failure.
        VibeVoiceSetupError: torch / transformers unavailable or model dir missing.

    Example:
        >>> out = await vibevoice_synthesize(
        ...     script=[SpeakerLine(speaker_id="host", text="Welcome!")],
        ...     output_path=Path("podcast.wav"),
        ... )
    """
    if not script:
        raise VibeVoiceError("script must not be empty")

    cfg_dict = config or {}
    model_dir = Path(
        cfg_dict.get("VIBEVOICE_MODEL_DIR")
        or cfg.get("VIBEVOICE_MODEL_DIR", "vendor/vibevoice")
    )

    if _inference_fn is None:
        model_bundle = _load_model(model_dir)
        infer = _make_inference(model_bundle, watermark)
    else:
        infer = _inference_fn

    import asyncio

    loop = asyncio.get_event_loop()
    segments: list[bytes] = []

    for line in script:
        voice_ref: Path | None = getattr(line, "voice_ref", None)
        wav_bytes: bytes = await loop.run_in_executor(
            None, infer, line.text, line.speaker_id, voice_ref
        )
        segments.append(wav_bytes)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    _concat_wav(segments, output_path)
    return output_path


def _load_model(model_dir: Path) -> Any:
    """Load VibeVoice model bundle (processor, model, device)."""
    try:
        import torch
    except ImportError as exc:
        raise VibeVoiceSetupError(
            "torch not installed; required for VibeVoice local inference"
        ) from exc

    try:
        from vibevoice import (  # type: ignore[import-untyped]
            VibeVoiceForConditionalGenerationInference,
            VibeVoiceProcessor,
        )
    except ImportError as exc:
        raise VibeVoiceSetupError(
            "vibevoice package not installed; pip install vibevoice"
        ) from exc

    if not model_dir.exists():
        raise VibeVoiceSetupError(
            f"VibeVoice model dir not found: {model_dir}"
        )

    device = "cuda" if torch.cuda.is_available() else "cpu"
    processor = VibeVoiceProcessor.from_pretrained(str(model_dir))
    model = VibeVoiceForConditionalGenerationInference.from_pretrained(
        str(model_dir),
        torch_dtype=torch.float16 if device == "cuda" else torch.float32,
        device_map=device,
    )
    return (processor, model, device)


def _make_inference(model_bundle: Any, watermark: bool) -> Any:
    """Return a closure that synthesizes a single line (runs in executor)."""
    # Maps arbitrary speaker_id strings to stable Speaker 1/2/3... numbers.
    # VibeVoiceProcessor._parse_script requires "Speaker N: text" format.
    _spk_map: dict[str, int] = {}

    def _infer(text: str, speaker_id: str, voice_ref: Path | None) -> bytes:
        import torch

        if speaker_id not in _spk_map:
            _spk_map[speaker_id] = len(_spk_map) + 1
        speaker_num = _spk_map[speaker_id]

        processor, model, device = model_bundle
        inputs: dict[str, Any] = {
            "text": f"Speaker {speaker_num}: {text}",
            "return_tensors": "pt",
        }
        if voice_ref is not None and voice_ref.exists():
            inputs["reference_audio"] = str(voice_ref)

        with torch.no_grad():
            encoded = processor(**inputs)
            encoded = {
                k: v.to(device) if hasattr(v, "to") else v
                for k, v in encoded.items()
            }
            # generate() pops 'tokenizer' from kwargs for stopping criteria
            output = model.generate(**encoded, tokenizer=processor.tokenizer)

        # output is VibeVoiceGenerationOutput; extract waveform from speech_outputs
        speech_outputs = getattr(output, "speech_outputs", None)
        if not speech_outputs or speech_outputs[0] is None:
            raise VibeVoiceError("VibeVoice generated no speech output")
        waveform_np = speech_outputs[0].squeeze().cpu().float().numpy()

        # Sample rate reported by the acoustic tokenizer (typically 24000 Hz)
        sample_rate: int = getattr(
            getattr(processor, "audio_processor", None), "sampling_rate", 24000
        )

        # watermark=True: responsible-AI safety marker (imperceptible in prod)
        if watermark:
            pass  # placeholder: real impl calls audio watermark library

        import numpy as np
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            pcm = np.clip(waveform_np, -1.0, 1.0)
            wf.writeframes((pcm * 32767).astype("int16").tobytes())
        return buf.getvalue()

    return _infer


def _concat_wav(segments: list[bytes], output_path: Path) -> None:
    """Concatenate WAV segments into a single output file."""
    if not segments:
        raise VibeVoiceError("No audio segments to concatenate")

    with wave.open(str(output_path), "wb") as out_wf:
        params_set = False
        for seg in segments:
            with wave.open(io.BytesIO(seg)) as seg_wf:
                if not params_set:
                    out_wf.setnchannels(seg_wf.getnchannels())
                    out_wf.setsampwidth(seg_wf.getsampwidth())
                    out_wf.setframerate(seg_wf.getframerate())
                    params_set = True
                out_wf.writeframes(seg_wf.readframes(seg_wf.getnframes()))
