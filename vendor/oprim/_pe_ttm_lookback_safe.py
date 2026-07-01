"""消除前视偏差的 TTM PE 计算 (oprim B8)."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field

from oprim._exceptions import OprimError


class PETTMResult(BaseModel):
    """lookback-safe TTM PE 结果.

    Attributes:
        pe_ttm: TTM 市盈率; ``None`` 表示 TTM EPS ≤ 0 (负盈利/亏损).
        eps_ttm: 滚动 4 季度 EPS 之和 (使用了 lag 后的合规数据).
        quarters_used: 实际用到的季度数 (≤4).
        as_of_date: 计算基准日.
        lag_days: 使用的滞后天数.
        warning: 数据不足时的警告信息 (如可用季度 <4).
    """

    pe_ttm: float | None
    eps_ttm: float
    quarters_used: int
    as_of_date: date
    lag_days: int
    warning: str | None = None


def pe_ttm_lookback_safe(
    *,
    price: float,
    eps_quarterly: list[tuple[date, float]],
    as_of_date: date,
    lag_days: int = 45,
) -> PETTMResult:
    """Compute TTM P/E without look-ahead bias by enforcing a publication lag.

    Only quarterly EPS figures whose **release date** is at least ``lag_days``
    before ``as_of_date`` are considered valid.  This prevents using earnings
    data that would not yet have been publicly available on that date.

    Args:
        price:          Stock price on ``as_of_date`` (must be > 0).
        eps_quarterly:  List of ``(release_date, eps_value)`` tuples, one per
                        quarter.  ``release_date`` is the date the report was
                        published.  May be unsorted.
        as_of_date:     Valuation date.
        lag_days:       Minimum days between release and usage.  Defaults to
                        45 (standard for A-share quarterly reports).

    Returns:
        :class:`PETTMResult`.  ``pe_ttm`` is ``None`` when ``eps_ttm`` ≤ 0.

    Raises:
        OprimError: If ``price`` ≤ 0 or no valid quarters found.

    Example:
        >>> from datetime import date
        >>> eps = [(date(2023, 4, 1), 0.5), (date(2023, 8, 1), 0.6),
        ...        (date(2023, 11, 1), 0.55), (date(2024, 1, 1), 0.65)]
        >>> r = pe_ttm_lookback_safe(price=20.0, eps_quarterly=eps,
        ...                          as_of_date=date(2024, 3, 1))
        >>> round(r.pe_ttm, 2)
        8.77
    """
    if price <= 0:
        raise OprimError(f"price must be > 0, got {price}")
    if lag_days < 0:
        raise OprimError(f"lag_days must be ≥ 0, got {lag_days}")

    valid = [
        (release, eps) for release, eps in eps_quarterly if (as_of_date - release).days >= lag_days
    ]
    if not valid:
        raise OprimError(f"No EPS data satisfies lag_days={lag_days} for as_of_date={as_of_date}")

    valid.sort(key=lambda t: t[0], reverse=True)
    most_recent_4 = valid[:4]
    eps_ttm = sum(e for _, e in most_recent_4)
    quarters_used = len(most_recent_4)
    warning = f"Only {quarters_used} quarters available (expected 4)" if quarters_used < 4 else None

    pe_ttm = round(price / eps_ttm, 4) if eps_ttm > 0 else None
    return PETTMResult(
        pe_ttm=pe_ttm,
        eps_ttm=round(eps_ttm, 6),
        quarters_used=quarters_used,
        as_of_date=as_of_date,
        lag_days=lag_days,
        warning=warning,
    )
