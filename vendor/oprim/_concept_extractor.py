"""oprim.concept_extractor — Extract concept list from text via single LLM call.

3O layer: oprim (single LLM call, obase.ProviderRegistry, no state).
Returns list of concepts as strings. Default unverified (A19 pattern).
"""

from __future__ import annotations

import re


def concept_extractor(
    *,
    text: str,
    max_concepts: int = 20,
    provider: str = "default",
) -> dict:
    """Extract concepts from text via LLM. Falls back to regex stub.

    Returns: {concepts: list[str], count: int, provider_used: str, error: str|None}
    Stub: extracts capitalized phrases as concepts.
    """
    result: dict = {
        "concepts": [],
        "count": 0,
        "provider_used": provider,
        "error": None,
    }

    if not text or not text.strip():
        return result

    try:
        # Stub: extract sequences of capitalized words as concepts
        # Matches one or more capitalized words (Title Case or ALL CAPS sequences)
        pattern = r"\b([A-Z][a-zA-Z]*(?:\s+[A-Z][a-zA-Z]*)*)\b"
        matches = re.findall(pattern, text)

        # Deduplicate while preserving order
        seen: set[str] = set()
        concepts: list[str] = []
        for match in matches:
            normalized = match.strip()
            if normalized and normalized not in seen:
                seen.add(normalized)
                concepts.append(normalized)

        concepts = concepts[:max_concepts]
        result["concepts"] = concepts
        result["count"] = len(concepts)
    except Exception as exc:
        result["error"] = str(exc)

    return result
