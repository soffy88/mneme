"""Resolve a ModelSpec into a Capabilities dataclass."""
from __future__ import annotations

from ._hicode_types import Capabilities, ModelSpec


def resolve_model_capabilities(model: ModelSpec) -> Capabilities:
    """Extract capability flags from *model* into a :class:`Capabilities` instance.

    Parameters
    ----------
    model:
        Source model specification.

    Returns
    -------
    Capabilities
        Populated from the model's support flags and context length.
    """
    return Capabilities(
        tools=model.supports_tools,
        vision=model.supports_vision,
        reasoning=model.supports_reasoning,
        max_context=model.context_length,
    )
