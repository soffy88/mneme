"""oprim.ocr_detect_text — OCR text detection from image bytes.

3O layer: oprim (single atomic OCR call via provider).
Uses tesseract or PaddleOCR via obase.ProviderRegistry if available.
Falls back to stub returning empty text for environments without OCR.
"""

from __future__ import annotations


def ocr_detect_text(
    *,
    image_bytes: bytes,
    language: str = "eng",
    provider: str = "default",
) -> dict:
    """Extract text from image bytes via OCR.

    Returns: {text: str, confidence: float|None, language: str, provider_used: str,
              error: str|None}
    Stub returns text="" when no OCR provider available.
    """
    result: dict = {
        "text": "",
        "confidence": None,
        "language": language,
        "provider_used": "stub",
        "error": None,
    }

    if not isinstance(image_bytes, (bytes, bytearray)):
        result["error"] = "image_bytes must be bytes"
        return result

    if len(image_bytes) == 0:
        result["provider_used"] = "stub"
        return result

    # Try pytesseract
    if provider in ("default", "tesseract"):
        try:
            import pytesseract  # type: ignore
            from PIL import Image  # type: ignore
            import io

            img = Image.open(io.BytesIO(image_bytes))
            data = pytesseract.image_to_data(
                img, lang=language, output_type=pytesseract.Output.DICT
            )
            text = pytesseract.image_to_string(img, lang=language)
            confs = [c for c in data.get("conf", []) if isinstance(c, (int, float)) and c >= 0]
            confidence = sum(confs) / len(confs) / 100.0 if confs else None
            result["text"] = text.strip()
            result["confidence"] = confidence
            result["provider_used"] = "tesseract"
            return result
        except ImportError:
            pass
        except Exception as exc:
            result["error"] = str(exc)
            result["provider_used"] = "tesseract"
            return result

    # Try PaddleOCR
    if provider in ("default", "paddleocr"):
        try:
            from paddleocr import PaddleOCR  # type: ignore
            import numpy as np  # type: ignore
            from PIL import Image  # type: ignore
            import io

            img = Image.open(io.BytesIO(image_bytes))
            img_array = np.array(img)
            ocr = PaddleOCR(use_angle_cls=True, lang=language, show_log=False)
            ocr_result = ocr.ocr(img_array, cls=True)
            lines = []
            confs = []
            if ocr_result:
                for line in ocr_result[0] or []:
                    if line and len(line) >= 2:
                        lines.append(line[1][0])
                        confs.append(float(line[1][1]))
            result["text"] = "\n".join(lines)
            result["confidence"] = sum(confs) / len(confs) if confs else None
            result["provider_used"] = "paddleocr"
            return result
        except ImportError:
            pass
        except Exception as exc:
            result["error"] = str(exc)
            result["provider_used"] = "paddleocr"
            return result

    # Stub — no OCR provider available
    return result
