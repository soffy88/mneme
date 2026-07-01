"""新闻冲击检测 — 关键财务事件 + 5min 价格异常波动 (oprim B9).

调用既有 oprim.financial_metric_extraction (1个oprim).
5min 波动率内嵌计算(inline),不调用其他 oprim — 满足 oprim 单一调用约定.
"""

from __future__ import annotations

import math
import statistics

from pydantic import BaseModel, Field

from oprim._detector_types import DetectorSignal, _now_utc
from oprim._exceptions import OprimError
from oprim.financial_metric_extraction import NewsItem, financial_metric_extraction


class NewsShockConfig(BaseModel):
    """新闻冲击检测阈值配置.

    Attributes:
        sentiment_threshold:   触发所需的情感分绝对值下限 (如 0.5).
        volatility_threshold:  5min 价格波动率下限 (如 0.01 表示 1%).
    """

    sentiment_threshold: float = Field(default=0.5, ge=0, le=1)
    volatility_threshold: float = Field(default=0.01, ge=0)


def _five_min_volatility(prices: list[float]) -> float:
    """Compute annualised realised volatility from 5-min close prices.

    Inline implementation — does not call any other oprim.
    Returns std of log-returns (un-annualised) for the detector's purposes.
    """
    if len(prices) < 2:
        return 0.0
    log_returns = [
        math.log(prices[i] / prices[i - 1]) for i in range(1, len(prices)) if prices[i - 1] > 0
    ]
    if len(log_returns) < 1:
        return 0.0
    return statistics.stdev(log_returns) if len(log_returns) > 1 else abs(log_returns[0])


def detect_news_shock(
    *,
    news: list[NewsItem],
    five_min_prices: list[float],
    config: NewsShockConfig = NewsShockConfig(),
) -> DetectorSignal | None:
    """Detect a news-driven price shock — significant sentiment hit AND abnormal 5-min volatility.

    Triggers when BOTH conditions are met:
    - :func:`oprim.financial_metric_extraction` extracts at least one metric whose
      ``abs(sentiment_score) ≥ config.sentiment_threshold``
    - Realised volatility of ``five_min_prices`` ≥ ``config.volatility_threshold``

    The 5-minute volatility is computed inline (std of log-returns) and does NOT
    call any additional oprim — satisfying the single-oprim-call convention.

    Args:
        news:            News items to analyse.  Empty list returns ``None``.
        five_min_prices: 5-minute close prices (oldest first, ≥ 2 bars required).
        config:          Threshold overrides.

    Returns:
        :class:`~oprim._detector_types.DetectorSignal` on trigger; ``None`` otherwise.

    Raises:
        OprimError: If ``five_min_prices`` has fewer than 2 elements.

    Example:
        >>> from oprim.financial_metric_extraction import NewsItem
        >>> news = [NewsItem(content="公司净利润同比暴增 300%, 超预期大幅盈利")]
        >>> prices = [10.0, 10.3, 10.6, 10.4, 10.8]
        >>> sig = detect_news_shock(news=news, five_min_prices=prices)
    """
    if len(five_min_prices) < 2:
        raise OprimError(f"five_min_prices must have ≥ 2 elements, got {len(five_min_prices)}")
    if not news:
        return None

    metrics = financial_metric_extraction(news=news)
    triggered_metrics = [m for m in metrics if abs(m.sentiment_score) >= config.sentiment_threshold]
    if not triggered_metrics:
        return None

    vol = _five_min_volatility(five_min_prices)
    if vol < config.volatility_threshold:
        return None

    max_sentiment = max(abs(m.sentiment_score) for m in triggered_metrics)
    if max_sentiment >= 0.8 and vol >= config.volatility_threshold * 2:
        severity = "critical"
    elif max_sentiment >= 0.6:
        severity = "high"
    else:
        severity = "medium"

    return DetectorSignal(
        detector_name="news_shock",
        severity=severity,
        triggered_at=_now_utc(),
        evidence={
            "triggered_metrics": [m.metric_name for m in triggered_metrics],
            "max_sentiment_score": round(max_sentiment, 4),
            "five_min_volatility": round(vol, 6),
            "news_count": len(news),
        },
    )
