"""政策事件抽取 (oprim)."""

from __future__ import annotations

import re
from typing import Any
from pydantic import BaseModel, Field

from oprim._exceptions import OprimError


class PolicyNews(BaseModel):
    """政策新闻."""
    content: str = Field(..., description="新闻正文")
    title: str | None = Field(None, description="标题")


class PolicyEvent(BaseModel):
    """抽取的政策事件."""
    event_type: str = Field(..., description="事件类型")
    severity: str = Field("moderate", description="严重程度 [minor|moderate|major|critical]")
    direction: str = Field("neutral", description="方向 [positive|negative|neutral]")
    days_ago: int = Field(0, description="距离当下的天数")
    source_excerpt: str | None = Field(None, description="来源片段")


def policy_event_extraction(
    *, 
    policies: list[PolicyNews]
) -> list[PolicyEvent]:
    """政策新闻抽取结构化事件(severity/direction). V1 规则实现.

    Args:
        policies: 政策相关新闻列表.

    Returns:
        抽取出的事件列表.
    """
    results: list[PolicyEvent] = []
    
    # 事件类型映射
    type_map = {
        "monetary": ["货币政策", "降准", "加息", "降息"],
        "fiscal": ["财政政策", "税收", "减税"],
        "industry": ["产业政策", "扶持", "补贴"],
    }
    
    # 严重程度关键词
    severity_map = {
        "critical": ["特大", "紧急", "历史性"],
        "major": ["重大", "显著", "重要"],
        "minor": ["微调", "局部"],
    }

    # 方向关键词
    pos_words = ["支持", "利好", "鼓励", "增长", "下调"]
    neg_words = ["限制", "处罚", "严查", "禁止", "上调"]

    for item in policies:
        text = item.content
        found_type = "unknown"
        for etype, kws in type_map.items():
            if any(kw in text for kw in kws):
                found_type = etype
                break
        
        if found_type == "unknown" and item.title:
            for etype, kws in type_map.items():
                if any(kw in item.title for kw in kws):
                    found_type = etype
                    break

        if found_type != "unknown" or any(kw in text for kw in ["政策", "法规", "通知"]):
            severity = "moderate"
            for slevel, skws in severity_map.items():
                if any(skw in text for skw in skws):
                    severity = slevel
                    break
            
            direction = "neutral"
            pos_hits = sum(1 for w in pos_words if w in text)
            neg_hits = sum(1 for w in neg_words if w in text)
            if pos_hits > neg_hits:
                direction = "positive"
            elif neg_hits > pos_hits:
                direction = "negative"

            results.append(PolicyEvent(
                event_type=found_type,
                severity=severity,
                direction=direction,
                days_ago=0, # V1 Stub: assume today
                source_excerpt=text[:100]
            ))
            
    return results
