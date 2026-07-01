"""金融指标抽取 (oprim)."""

from __future__ import annotations

import re
from typing import Any
from pydantic import BaseModel, Field

from oprim._exceptions import OprimError


class NewsItem(BaseModel):
    """新闻条目."""
    content: str = Field(..., description="新闻正文")
    source: str | None = Field(None, description="来源")


class FinancialMetric(BaseModel):
    """抽取的财务指标."""
    metric_name: str = Field(..., description="指标名称")
    value: float | None = Field(None, description="数值")
    sentiment_score: float = Field(0.0, description="情感分 [-1, 1]")
    source_excerpt: str | None = Field(None, description="来源片段")


def financial_metric_extraction(
    *, 
    news: list[NewsItem]
) -> list[FinancialMetric]:
    """从中文财经新闻抽取财务指标 + 情感分(V1 规则实现).

    Args:
        news: 新闻列表.

    Returns:
        抽取出的指标列表.
    """
    results: list[FinancialMetric] = []
    
    # 简单的规则提取示例 (V1 Stub)
    patterns = {
        "revenue": ["营业收入", "营收"],
        "net_profit": ["净利润", "净利"],
    }
    
    # 情感关键词
    pos_words = ["增长", "提升", "利好", "大增", "新高"]
    neg_words = ["下降", "减少", "利空", "亏损", "下滑"]

    for item in news:
        text = item.content
        for metric, keywords in patterns.items():
            for kw in keywords:
                # 匹配 "关键词 [达到/为/是/：/:/下降/减少]? 123.45 (亿/万)?"
                m = re.search(rf"{kw}\s*[：:为是约达到增至减至下降减少]*\s*([\d.]+)\s*([亿万]?)", text)
                if m:
                    val = float(m.group(1))
                    unit = m.group(2)
                    if unit == "亿":
                        val *= 1e8
                    elif unit == "万":
                        val *= 1e4
                    
                    # 简单情感判定
                    sentiment = 0.0
                    for pw in pos_words:
                        if pw in text: sentiment += 0.2
                    for nw in neg_words:
                        if nw in text: sentiment -= 0.2
                    sentiment = max(-1.0, min(1.0, sentiment))

                    results.append(FinancialMetric(
                        metric_name=metric,
                        value=val,
                        sentiment_score=sentiment,
                        source_excerpt=text[max(0, m.start()-10):m.end()+10]
                    ))
                    break # 找到一个关键词即可
    
    return results
