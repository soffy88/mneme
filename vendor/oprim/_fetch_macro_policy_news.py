"""政策新闻采集 — 央行/财政部/发改委/证监会/商务部 (oprim B7)."""

from __future__ import annotations

import asyncio
from datetime import date
from typing import Any, Literal

from oprim._macro_types import MacroDataPoint, MacroFetchError, _filter_by_date, _guard_source

# akshare API: ak.news_economic_baidu()
# Expected columns: 发布时间, 标题, 摘要
# Note: akshare's news API returns Chinese financial news headlines.
# value is set to 0.0 (sentinel); text content lives in metadata.
_DATE_COL = "发布时间"
_TITLE_COL = "标题"
_SUMMARY_COL = "摘要"

_POLICY_KEYWORDS = (
    "央行",
    "货币政策",
    "财政部",
    "发改委",
    "证监会",
    "商务部",
    "降准",
    "降息",
    "财政",
)


def _akshare_fetch_policy_news() -> list[dict[str, Any]]:
    """Call akshare and return raw rows. Sync — run via asyncio.to_thread.

    Note: akshare news APIs may require cookie/session state on some versions.
    If unavailable, MacroFetchError is raised by the async wrapper.
    """
    import akshare as ak  # lazy import: pip install akshare

    df = ak.news_economic_baidu()
    return df.to_dict("records")


def _is_policy_relevant(title: str, summary: str) -> bool:
    text = title + summary
    return any(kw in text for kw in _POLICY_KEYWORDS)


async def fetch_macro_policy_news(
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    source: Literal["wind", "akshare", "tushare"] = "akshare",
) -> list[MacroDataPoint]:
    """Fetch policy-relevant news headlines from five major regulators via akshare.

    Filters for: 央行, 财政部, 发改委, 证监会, 商务部 and monetary policy keywords.
    Each item yields one :class:`~oprim._macro_types.MacroDataPoint` where:
    - ``indicator = "policy_news"``
    - ``value = 0.0`` (sentinel — numeric value is not applicable for text events)
    - ``metadata["title"]``, ``metadata["summary"]`` contain the news text

    Note: ``ak.news_economic_baidu()`` scrapes Baidu Finance; availability may vary.

    Args:
        start_date: Inclusive lower bound.
        end_date:   Inclusive upper bound.
        source:     Only ``"akshare"`` is freely available.

    Returns:
        List of :class:`~oprim._macro_types.MacroDataPoint` sorted by date ascending.

    Raises:
        MacroFetchError: On licensed source, network error, or unexpected response.

    Example:
        >>> pts = await fetch_macro_policy_news(start_date=date(2024, 1, 1))
        >>> pts[0].indicator
        'policy_news'
    """
    _guard_source(source)
    try:
        rows = await asyncio.to_thread(_akshare_fetch_policy_news)
    except MacroFetchError:
        raise
    except Exception as exc:
        raise MacroFetchError(f"fetch_macro_policy_news failed: {exc}") from exc

    points: list[MacroDataPoint] = []
    for row in rows:
        raw_date = row.get(_DATE_COL)
        title = str(row.get(_TITLE_COL, ""))
        summary = str(row.get(_SUMMARY_COL, ""))
        if raw_date is None:
            continue
        try:
            obs_date = date.fromisoformat(str(raw_date)[:10])
        except ValueError:
            continue
        if not _is_policy_relevant(title, summary):
            continue
        points.append(
            MacroDataPoint(
                indicator="policy_news",
                date=obs_date,
                value=0.0,
                metadata={"source": source, "title": title, "summary": summary},
            )
        )

    points.sort(key=lambda p: p.date)
    return _filter_by_date(points, start_date, end_date)
