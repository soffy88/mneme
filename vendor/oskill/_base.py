"""Shared type aliases for oskill."""  # pragma: no cover

from typing import Callable

import numpy as np
import pandas as pd

ArrayLike = np.ndarray | pd.Series
StatisticFn = Callable[[np.ndarray], float]
