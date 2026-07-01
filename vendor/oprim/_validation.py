"""Shared input validation utilities for oprim."""  # pragma: no cover

import numpy as np

from oprim._base import ArrayLike


def validate_positive_array(data: ArrayLike, name: str = "data") -> np.ndarray:
    """Validate and convert input to numpy array with all positive values."""
    arr = np.asarray(data, dtype=np.float64)
    if arr.size == 0:
        raise ValueError(f"{name} must not be empty")
    if np.any(arr <= 0):
        raise ValueError(f"{name} must contain only positive values")
    return arr


def validate_no_nan(data: ArrayLike, name: str = "data") -> np.ndarray:
    """Validate and convert input to numpy array with no NaN values."""
    arr = np.asarray(data, dtype=np.float64)
    if np.any(np.isnan(arr)):
        raise ValueError(f"{name} must not contain NaN values")
    return arr


def validate_min_length(data: ArrayLike, min_len: int, name: str = "data") -> np.ndarray:
    """Validate and convert input to numpy array with minimum length."""
    arr = np.asarray(data, dtype=np.float64)
    if arr.shape[0] < min_len:
        raise ValueError(f"{name} must have at least {min_len} elements, got {arr.shape[0]}")
    return arr
