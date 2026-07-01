"""止损合规判定 (oprim B8)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from oprim._exceptions import OprimError


class StopLossResult(BaseModel):
    """止损合规判定结果.

    Attributes:
        triggered: 是否触发止损.
        current_loss_pct: 当前亏损百分比 (正数=亏损, 负数=盈利).
        stop_loss_pct: 配置的最大止损百分比阈值.
        action: 建议动作 — ``"hold"`` 或 ``"stop_loss"``.
    """

    triggered: bool
    current_loss_pct: float
    stop_loss_pct: float = Field(..., gt=0)
    action: Literal["hold", "stop_loss"]


def stop_loss_compliance_check(
    *,
    entry_price: float,
    current_price: float,
    stop_loss_pct: float,
) -> StopLossResult:
    """Check whether a position has breached its stop-loss level.

    ``current_loss_pct`` = (entry_price − current_price) / entry_price × 100.
    A positive value means the position is in loss; negative means profit.
    ``triggered`` is ``True`` when ``current_loss_pct >= stop_loss_pct``.

    Args:
        entry_price:   Price at which the position was opened (must be > 0).
        current_price: Latest market price (must be > 0).
        stop_loss_pct: Maximum allowable loss in percentage points (e.g. ``8.0``
                       for 8 %).  Must be > 0.

    Returns:
        :class:`StopLossResult`.

    Raises:
        OprimError: If any price is non-positive or ``stop_loss_pct`` ≤ 0.

    Example:
        >>> r = stop_loss_compliance_check(entry_price=10.0, current_price=9.1,
        ...                                stop_loss_pct=8.0)
        >>> r.triggered
        True
        >>> r.action
        'stop_loss'
    """
    if entry_price <= 0:
        raise OprimError(f"entry_price must be > 0, got {entry_price}")
    if current_price <= 0:
        raise OprimError(f"current_price must be > 0, got {current_price}")
    if stop_loss_pct <= 0:
        raise OprimError(f"stop_loss_pct must be > 0, got {stop_loss_pct}")

    loss_pct = round((entry_price - current_price) / entry_price * 100, 4)
    triggered = loss_pct >= stop_loss_pct
    return StopLossResult(
        triggered=triggered,
        current_loss_pct=loss_pct,
        stop_loss_pct=stop_loss_pct,
        action="stop_loss" if triggered else "hold",
    )
