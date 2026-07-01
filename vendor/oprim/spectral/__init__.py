"""Spectral analysis primitives submodule."""
from __future__ import annotations

from oprim.spectral.eigengap import spectral_eigengap_detect
from oprim.spectral.ledoit_wolf import ledoit_wolf_shrinkage
from oprim.spectral.marchenko_pastur import marchenko_pastur_threshold
from oprim.spectral.rie import rotationally_invariant_estimator

__all__ = [
    "marchenko_pastur_threshold",
    "rotationally_invariant_estimator",
    "ledoit_wolf_shrinkage",
    "spectral_eigengap_detect",
]
