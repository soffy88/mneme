"""Shared type aliases and base utilities for oprim."""  # pragma: no cover

from __future__ import annotations

import numpy as np
import pandas as pd

ArrayLike = np.ndarray | pd.Series | list[float]
Numeric = int | float | np.integer | np.floating
