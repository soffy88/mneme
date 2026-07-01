from typing import Any
from pydantic import BaseModel

class TranslationResult(BaseModel):
    text: str
    provider: str = "mock"
    model: str = "mock"
    input_tokens: int = 10
    output_tokens: int = 10
    cost_usd: float = 0.001
    source_lang: str = "en"
    target_lang: str = "zh"
    detected_source_language: str = "en"
    billed_characters: int = 10
