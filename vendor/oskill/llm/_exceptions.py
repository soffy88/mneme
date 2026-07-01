"""Custom exceptions for LLM integration primitives."""


class LLMResponseFormatError(ValueError):
    """Raised when the LLM response cannot be parsed as the expected format (e.g. JSON)."""


class LLMResponseValidationError(ValueError):
    """Raised when the LLM response fails JSON schema validation."""
