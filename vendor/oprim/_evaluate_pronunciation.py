"""P-2: evaluate_pronunciation — single-call pronunciation assessment via ProviderRegistry.

COMPLIANCE NOTICE: Callers are responsible for registering a provider that has
completed filing (备案) with China's Cyberspace Administration (CAC). Recommended
providers: 讯飞开放平台 / 腾讯云 / 阿里云 AI. This library does NOT hard-code any
specific provider; service selection is delegated entirely to the caller.

Prohibition: LLM MUST NOT be used to simulate pronunciation scores. All scores
must originate from a genuine acoustic model exposed through the registered provider.
"""

from __future__ import annotations

from oprim._mneme_speech_types import PronunciationResult


async def evaluate_pronunciation(
    *,
    audio_b64: str,
    reference_text: str,
    provider: str = "default",
) -> PronunciationResult:
    """Evaluate spoken pronunciation against a reference text.

    Delegates to the "pronunciation" provider in ProviderRegistry. The provider
    must be a genuine ASR/TTS-evaluation endpoint — LLM simulation is prohibited.

    Args:
        audio_b64: Base-64 encoded audio of the speaker's utterance.
        reference_text: The expected text the speaker should have said.
        provider: Provider name registered under category "pronunciation".

    Returns:
        PronunciationResult with overall, fluency, accuracy scores and word-level detail.

    Raises:
        ValueError: reference_text is empty.
        RuntimeError: provider not registered.
    """
    if not reference_text:
        raise ValueError("reference_text must not be empty")

    from obase.provider_registry import ProviderRegistry

    caller = ProviderRegistry.get().generic("pronunciation", provider)
    raw = await caller(audio_b64=audio_b64, reference_text=reference_text)

    if isinstance(raw, PronunciationResult):
        return raw

    return PronunciationResult(
        overall_score=float(raw.get("overall_score", 0.0)),
        fluency_score=float(raw.get("fluency_score", 0.0)),
        accuracy_score=float(raw.get("accuracy_score", 0.0)),
        word_scores=list(raw.get("word_scores", [])),
    )
