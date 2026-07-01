"""时间序列 60/20/20 切分 (oprim B8)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from oprim._exceptions import OprimError


class TrainValOOSSplit(BaseModel):
    """Train / Val / OOS 切分结果.

    Attributes:
        train:         训练集 (前 ``train_ratio`` 部分).
        val:           验证集 (中间 ``val_ratio`` 部分).
        oos:           样本外测试集 (剩余部分).
        split_indices: ``(val_start, oos_start)`` — val 和 oos 起始索引.
        train_ratio:   实际使用的训练集比例.
        val_ratio:     实际使用的验证集比例.
    """

    train: list[Any]
    val: list[Any]
    oos: list[Any]
    split_indices: tuple[int, int]
    train_ratio: float
    val_ratio: float


def train_val_oos_splitter(
    *,
    data: list[Any],
    train_ratio: float = 0.6,
    val_ratio: float = 0.2,
) -> TrainValOOSSplit:
    """Split a time-ordered sequence into train / validation / out-of-sample sets.

    The split is strictly sequential — no shuffling — to preserve temporal
    order and prevent information leakage.

    Args:
        data:        Time-ordered list.  Must have ≥ 3 elements.
        train_ratio: Fraction for training set.  Defaults to 0.6 (60 %).
        val_ratio:   Fraction for validation set.  Defaults to 0.2 (20 %).
                     The OOS set receives the remaining ``1 − train_ratio − val_ratio``.

    Returns:
        :class:`TrainValOOSSplit`.

    Raises:
        OprimError: If ``data`` has fewer than 3 elements, ratios sum to > 1,
                    or either ratio is ≤ 0.

    Example:
        >>> s = train_val_oos_splitter(data=list(range(100)))
        >>> len(s.train), len(s.val), len(s.oos)
        (60, 20, 20)
    """
    if len(data) < 3:
        raise OprimError(f"data must have ≥ 3 elements, got {len(data)}")
    if train_ratio <= 0 or val_ratio <= 0:
        raise OprimError("train_ratio and val_ratio must be > 0")
    if train_ratio + val_ratio >= 1.0:
        raise OprimError(f"train_ratio + val_ratio must be < 1.0, got {train_ratio + val_ratio}")

    n = len(data)
    val_start = int(n * train_ratio)
    oos_start = int(n * (train_ratio + val_ratio))

    # Guarantee at least 1 element in each split
    val_start = max(1, val_start)
    oos_start = max(val_start + 1, oos_start)
    if oos_start >= n:
        oos_start = n - 1

    return TrainValOOSSplit(
        train=list(data[:val_start]),
        val=list(data[val_start:oos_start]),
        oos=list(data[oos_start:]),
        split_indices=(val_start, oos_start),
        train_ratio=train_ratio,
        val_ratio=val_ratio,
    )
