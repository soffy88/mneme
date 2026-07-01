"""A 股 T+N 持仓锁定判定 (oprim Step-12)."""

from __future__ import annotations

from datetime import date


def t_plus_n_blocked(
    *,
    entry_date: date,
    current_date: date,
    t_plus_n: int,
) -> bool:
    """A 股 T+N 持仓锁定判定。

    Args:
        entry_date: 买入日期
        current_date: 当前评估日期
        t_plus_n: 锁定天数(自然日)。A 股标准 1(T+1,买入次日可卖)。T+0 = 0

    Returns:
        是否仍在锁定期(True=不能卖)。逻辑:current_date - entry_date < t_plus_n

    Raises:
        ValueError: t_plus_n < 0 或 current_date < entry_date

    Example:
        >>> from datetime import date
        >>> t_plus_n_blocked(entry_date=date(2026,5,28), current_date=date(2026,5,28), t_plus_n=1)
        True
        >>> t_plus_n_blocked(entry_date=date(2026,5,28), current_date=date(2026,5,29), t_plus_n=1)
        False
    """
    if t_plus_n < 0:
        raise ValueError(f"t_plus_n must be >= 0, got {t_plus_n}")
    if current_date < entry_date:
        raise ValueError(f"current_date ({current_date}) must be >= entry_date ({entry_date})")

    days_held = (current_date - entry_date).days
    return days_held < t_plus_n
