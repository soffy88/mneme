"""Optional sentence explanation — never writes mastery."""

from __future__ import annotations

from typing import Any
from uuid import UUID


async def explain_sentence_safe(
    *,
    student_id: UUID,
    media_id: UUID,
    segment_id: UUID,
    text: str,
    nearby: list[str] | None = None,
) -> dict[str, Any]:
    """Best-effort explanation via existing LLM registry; degrade if unavailable."""

    del student_id  # used only for future personalization; never mastery write
    context = {
        "media_id": str(media_id),
        "segment_id": str(segment_id),
        "text": text,
        "nearby": nearby or [],
    }
    try:
        from obase.provider_registry import get_chat_provider  # type: ignore

        provider = get_chat_provider()
        prompt = (
            "Explain this sentence for a language learner. "
            "Do not claim mastery. Keep it concise.\n"
            f"Sentence: {text}\n"
            f"Nearby: {' | '.join((nearby or [])[:3])}"
        )
        explanation = await provider.complete(prompt)  # type: ignore[attr-defined]
        return {
            "status": "ok",
            "explanation": explanation,
            "mastery_modified": False,
            "provenance": {
                "provider": getattr(provider, "name", "unknown"),
                "model_version": getattr(provider, "model", None),
                "context_class": "immersive_sentence_explain",
            },
            "context": context,
        }
    except Exception:  # noqa: BLE001
        return {
            "status": "degraded",
            "explanation": None,
            "message": "explanation provider unavailable; player remains usable",
            "mastery_modified": False,
            "context": context,
        }
