"""缩量调整后放量突破检测 — 华安规律 ① 通用命名 (oprim B8)."""

from __future__ import annotations

from pydantic import BaseModel

from oprim._exceptions import OprimError


class VolumeBreakoutResult(BaseModel):
    """缩量突破检测结果.

    Attributes:
        signal:         检测到有效形态时为 ``True``.
        dryup_start_idx: 缩量期开始的索引 (``signal=True`` 时有值).
        breakout_idx:   放量突破日的索引 (``signal=True`` 时有值).
        dryup_avg_vol:  缩量期平均成交量.
        breakout_vol:   突破日成交量.
    """

    signal: bool
    dryup_start_idx: int | None = None
    breakout_idx: int | None = None
    dryup_avg_vol: float | None = None
    breakout_vol: float | None = None


def detect_volume_dryup_breakout(
    *,
    close: list[float],
    volume: list[float],
    lookback: int = 20,
    dryup_pct: float = 0.7,
    breakout_vol_mult: float = 1.5,
    min_dryup_days: int = 3,
) -> VolumeBreakoutResult:
    """Detect a volume dry-up consolidation followed by a high-volume breakout.

    Pattern (华安规律 ①):
    1. **Dry-up period**: a consecutive run of ≥ ``min_dryup_days`` bars where
       volume is below ``dryup_pct × avg_vol`` (rolling ``lookback`` average).
    2. **Breakout bar**: the bar immediately after the dry-up has volume ≥
       ``breakout_vol_mult × avg_vol`` AND close > previous close.

    The function scans from the most recent bar backwards.

    Args:
        close:              Closing prices (time-ordered, oldest first).
        volume:             Corresponding volume series.
        lookback:           Rolling window for computing average volume.
        dryup_pct:          Volume threshold for dry-up bars (fraction of avg).
        breakout_vol_mult:  Minimum volume multiple for the breakout bar.
        min_dryup_days:     Minimum consecutive dry-up bars required.

    Returns:
        :class:`VolumeBreakoutResult`.

    Raises:
        OprimError: If ``close`` and ``volume`` lengths differ, or are shorter
                    than ``lookback + min_dryup_days + 1``.

    Example:
        >>> c = [10.0] * 25 + [10.5]
        >>> v = [1000.0] * 20 + [400.0, 400.0, 400.0, 400.0, 400.0] + [2500.0]
        >>> r = detect_volume_dryup_breakout(close=c, volume=v)
        >>> r.signal
        True
    """
    n = len(close)
    if len(volume) != n:
        raise OprimError(f"close and volume must have equal length, got {n} vs {len(volume)}")
    min_len = lookback + min_dryup_days + 1
    if n < min_len:
        raise OprimError(f"Sequence length {n} is less than required {min_len}")
    if dryup_pct <= 0 or dryup_pct >= 1:
        raise OprimError(f"dryup_pct must be in (0, 1), got {dryup_pct}")
    if breakout_vol_mult <= 1:
        raise OprimError(f"breakout_vol_mult must be > 1, got {breakout_vol_mult}")

    # Compute rolling average volume for each bar (using preceding lookback bars)
    avg_vols = [sum(volume[max(0, i - lookback) : i]) / min(i, lookback) for i in range(1, n + 1)]

    # Scan backwards: find the most recent valid breakout pattern
    for breakout_i in range(n - 1, lookback + min_dryup_days - 1, -1):
        avg = avg_vols[breakout_i - 1]
        if avg <= 0:
            continue
        # Check breakout bar
        if volume[breakout_i] < breakout_vol_mult * avg:
            continue
        if close[breakout_i] <= close[breakout_i - 1]:
            continue
        # Count dry-up bars immediately before breakout
        dryup_end = breakout_i - 1
        dryup_start = dryup_end
        while (
            dryup_start > lookback and volume[dryup_start] < dryup_pct * avg_vols[dryup_start - 1]
        ):
            dryup_start -= 1
        consecutive = dryup_end - dryup_start
        if consecutive >= min_dryup_days:
            dryup_vols = volume[dryup_start : dryup_end + 1]
            return VolumeBreakoutResult(
                signal=True,
                dryup_start_idx=dryup_start,
                breakout_idx=breakout_i,
                dryup_avg_vol=round(sum(dryup_vols) / len(dryup_vols), 2),
                breakout_vol=volume[breakout_i],
            )

    return VolumeBreakoutResult(signal=False)
