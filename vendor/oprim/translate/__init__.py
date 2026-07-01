from pydantic import BaseModel

class TranslationResult(BaseModel):
    text: str
    detected_source_language: str
    billed_characters: int

class TerminologyGlossary(BaseModel):
    pass

async def translate_document_async(*args, **kwargs):
    return TranslationResult(text="translated", detected_source_language="en", billed_characters=10)
