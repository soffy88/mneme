"""oskill.image_qa — Image question-answering via vision LLM.

3O layer: oskill (≥2 oprim composition, stateless).

Internal oprim composition:
    - oprim.concept_extractor: extract concepts from generated answer text
    - oprim.ocr_detect_text: extract any text visible in the image
    (Vision LLM call for the main QA is oprim-equivalent via obase.ProviderRegistry)
"""

from __future__ import annotations

from oprim import concept_extractor, ocr_detect_text


def image_qa(
    *,
    image_bytes: bytes,
    question: str,
    provider: str = "default",
    extract_concepts: bool = True,
) -> dict:
    """Answer a question about an image using vision LLM.

    Runs OCR to extract visible text from the image, then calls a vision LLM
    stub to produce an answer, and optionally runs concept_extractor over the
    answer text.

    Internal oprim composition:
        ocr_detect_text extracts text visible in the image.
        concept_extractor derives key concepts from the generated answer.

    Returns: {
        answer: str,
        ocr_text: str,
        concepts: list[str],
        confidence: float | None,
        provider_used: str,
        error: str | None,
    }
    """
    result: dict = {
        "answer": "",
        "ocr_text": "",
        "concepts": [],
        "confidence": None,
        "provider_used": provider,
        "error": None,
    }

    # 1. OCR: extract visible text from image
    ocr_result = ocr_detect_text(image_bytes=image_bytes, provider=provider)
    if ocr_result.get("error"):
        result["error"] = ocr_result["error"]
        result["provider_used"] = ocr_result.get("provider_used", provider)
        return result
    result["ocr_text"] = ocr_result.get("text", "")

    # 2. Vision LLM call (stub — returns placeholder answer)
    # In production this delegates to obase.ProviderRegistry vision model.
    try:
        answer = _vision_llm_stub(
            image_bytes=image_bytes,
            question=question,
            provider=provider,
        )
    except Exception as exc:
        result["error"] = str(exc)
        return result

    result["answer"] = answer
    result["confidence"] = None  # stub: no confidence score

    # 3. Concept extraction from the answer text
    if extract_concepts and answer:
        concept_result = concept_extractor(text=answer, provider=provider)
        result["concepts"] = concept_result.get("concepts", [])
    else:
        result["concepts"] = []

    return result


def _vision_llm_stub(*, image_bytes: bytes, question: str, provider: str) -> str:
    """Stub vision LLM call. Returns placeholder answer."""
    return f"[vision-stub] Answer to '{question}' (image size: {len(image_bytes)} bytes)"
