"""Filter a model catalog to curated models only."""
from __future__ import annotations

from ._hicode_types import ModelSpec


def filter_curated_models(catalog: list[ModelSpec]) -> list[ModelSpec]:
    """Return models from *catalog* where ``curated`` is True, preserving order.

    Parameters
    ----------
    catalog:
        ``list[ModelSpec]`` to filter.

    Returns
    -------
    list[ModelSpec]
        Subset of *catalog* with ``curated == True``.
    """
    return [m for m in catalog if m.curated]
