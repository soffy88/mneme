"""政策事件与行业归因 (oprim)."""

from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field

from oprim._exceptions import OprimError
from oprim.policy_event_extraction import PolicyEvent


class IndustryImpact(BaseModel):
    """行业受影响情况."""
    industry: str = Field(..., description="行业名称")
    impact_direction: str = Field(..., description="影响方向 [positive|negative|uncertain]")
    severity: str = Field(..., description="严重程度")
    days_ago: int = Field(..., description="事件发生的时长")


def industry_attribution(
    *, 
    events: list[PolicyEvent], 
    industry: dict[str, str]
) -> list[IndustryImpact]:
    """政策事件 → 受影响行业归因(纯映射, 无 LLM).

    Args:
        events: 政策事件列表.
        industry: 关键词到行业的映射 (例如: {"新能源": "电力设备", "房市": "房地产"}).

    Returns:
        受影响行业列表.
    """
    results: list[IndustryImpact] = []
    
    # 行业受政策类型影响的倾向性 (简化版)
    # monetary/fiscal stimulus -> positive for most
    # regulation/crackdown -> negative for most
    
    for event in events:
        impact_dir = event.direction
        if impact_dir == "neutral":
            if event.event_type in ("stimulus", "monetary", "fiscal"):
                impact_dir = "positive"
            elif event.event_type in ("regulation", "crackdown"):
                impact_dir = "negative"
            else:
                impact_dir = "uncertain"

        # 检查来源片段中的行业关键词
        if event.source_excerpt:
            for kw, ind_name in industry.items():
                if kw in event.source_excerpt:
                    results.append(IndustryImpact(
                        industry=ind_name,
                        impact_direction=impact_dir,
                        severity=event.severity,
                        days_ago=event.days_ago
                    ))
                    
    return results
