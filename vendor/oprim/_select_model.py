"""Select the best model from a catalog for a given task hint."""
from __future__ import annotations

from ._hicode_types import ModelSpec, TaskHint


def select_model(*, task: TaskHint, catalog: list[ModelSpec]) -> str:
    """Return the model id best suited for *task* from *catalog*.

    Parameters
    ----------
    task:
        Capability requirements for the task.
    catalog:
        ``list[ModelSpec]`` of available models.

    Raises
    ------
    ValueError
        If *catalog* is empty or no model satisfies all requirements.
    """
    if not catalog:
        raise ValueError("catalog is empty")

    candidates: list[ModelSpec] = []
    for model in catalog:
        if task.needs_tools and not model.supports_tools:
            continue
        if task.needs_vision and not model.supports_vision:
            continue
        if task.needs_reasoning and not model.supports_reasoning:
            continue
        if task.min_context > model.context_length:
            continue
        candidates.append(model)

    if not candidates:
        raise ValueError("no model for task")

    # Prefer lowest cost_per_input_token; stable sort keeps catalog order on ties.
    best = min(candidates, key=lambda m: m.cost_per_input_token)
    return best.id
