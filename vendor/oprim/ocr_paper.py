"""OCR a math paper/image using a Vision-Language Model.

Async, single VLM call.  Returns extracted text with LaTeX math notation.

Version: oprim v3.5.0
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class OCRPaperInput:
    """Input for OCR of a math paper image.

    Attributes
    ----------
    image_b64 : str
        Base-64 encoded image (PNG/JPEG).
    image_url : str | None
        Alternatively, a URL to the image.
    language : str
        Language hint for OCR ("zh-CN", "en", etc.).
    extract_math : bool
        If True, convert math to LaTeX notation.
    system : str | None
        Optional system prompt override.
    """

    image_b64: str = ""
    image_url: str | None = None
    language: str = "zh-CN"
    extract_math: bool = True
    system: str | None = None


@dataclass(frozen=True)
class OCRPaperResult:
    """Result of OCR on a math paper.

    Attributes
    ----------
    raw_text : str
        Full extracted text.
    math_expressions : list[str]
        Detected LaTeX math expressions.
    structured_questions : list[dict]
        Detected Q&A structure (question number + body).
    confidence : float
        Overall confidence score (0.0 to 1.0).
    success : bool
    error : str
    """

    raw_text: str = ""
    math_expressions: list[str] = field(default_factory=list)
    structured_questions: list[dict] = field(default_factory=list)
    confidence: float = 1.0
    success: bool = True
    error: str = ""


_OCR_SYSTEM = (
    "You are a math OCR assistant. Extract all text and mathematical expressions "
    "from the provided image. Render math as LaTeX enclosed in $..$ (inline) or "
    "$$...$$ (display). Preserve question numbers and structure. Return JSON with "
    'keys: "raw_text" (str), "math_expressions" (list of LaTeX strings), '
    '"structured_questions" (list of {number, body} dicts), "confidence" (float 0.0-1.0).'
)


async def ocr_paper(
    inp: OCRPaperInput,
    *,
    caller: Any,
    model: str = "claude-sonnet-4-6",
    max_tokens: int = 4096,
) -> OCRPaperResult:
    """OCR a math paper image using a VLM.

    Parameters
    ----------
    inp : OCRPaperInput
    caller : Any
        LLMCaller protocol instance (injected by caller).
    model : str
    max_tokens : int

    Returns
    -------
    OCRPaperResult
    """
    import json

    from oprim.llm._llm_complete import llm_complete

    system = inp.system or _OCR_SYSTEM

    # Build image content block
    if inp.image_url:
        content = [
            {
                "type": "image",
                "source": {"type": "url", "url": inp.image_url},
            },
            {
                "type": "text",
                "text": f"Extract all text and math from this image. Language: {inp.language}. Return JSON.",
            },
        ]
    elif inp.image_b64:
        content = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": inp.image_b64,
                },
            },
            {
                "type": "text",
                "text": f"Extract all text and math from this image. Language: {inp.language}. Return JSON.",
            },
        ]
    else:
        return OCRPaperResult(
            success=False,
            error="Must provide either image_b64 or image_url",
        )

    messages = [{"role": "user", "content": content}]

    try:
        response = await llm_complete(
            messages,
            caller=caller,
            system=system,
            model=model,
            max_tokens=max_tokens,
        )

        raw = response.text.strip()

        # Parse JSON response
        if raw.startswith("```"):
            raw = raw.split("```", 2)[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip().rstrip("`")

        data = json.loads(raw)
        return OCRPaperResult(
            raw_text=data.get("raw_text", ""),
            math_expressions=data.get("math_expressions", []),
            structured_questions=data.get("structured_questions", []),
            confidence=float(data.get("confidence", 1.0)),
            success=True,
        )

    except Exception as exc:
        return OCRPaperResult(success=False, error=str(exc))
