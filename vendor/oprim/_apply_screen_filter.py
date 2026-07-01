"""配置驱动选股过滤 (oprim)."""

from __future__ import annotations

from typing import Literal
import pandas as pd
from pydantic import BaseModel, Field

from oprim._exceptions import OprimError


class ScreenRule(BaseModel):
    """选股规则."""
    field: str = Field(..., description="列名")
    op: Literal["gt", "lt", "gte", "lte", "eq", "between", "flag"] = Field(..., description="操作符")
    threshold: float | tuple[float, float] | bool = Field(..., description="阈值")
    reason: str = Field(..., description="过滤理由")


class ScreenResult(BaseModel):
    """过滤结果."""
    passed: list[str] = Field(..., description="通过的代码列表")
    rejected: list[dict] = Field(..., description="被剔除的详情 [{symbol, failed_rule, reason}]")
    stats: dict = Field(..., description="统计信息")


def apply_screen_filter(
    *, 
    candidates: pd.DataFrame, 
    rules: list[ScreenRule]
) -> ScreenResult:
    """配置驱动选股过滤. 纯 DataFrame 过滤 + 规则匹配.

    Args:
        candidates: 候选股数据 DataFrame, 必须包含 'symbol' 列.
        rules: 过滤规则列表.

    Returns:
        ScreenResult(passed, rejected, stats).
    """
    if "symbol" not in candidates.columns:
        raise OprimError("Candidates DataFrame must contain 'symbol' column")

    df = candidates.copy()
    rejected_list: list[dict] = []
    
    # 初始状态
    passed_mask = pd.Series(True, index=df.index)
    
    for rule in rules:
        if rule.field not in df.columns:
            # 如果字段不存在，视情况报错或跳过
            continue
            
        field_series = df[rule.field]
        rule_mask = pd.Series(True, index=df.index)
        
        if rule.op == "gt":
            rule_mask = field_series > rule.threshold
        elif rule.op == "lt":
            rule_mask = field_series < rule.threshold
        elif rule.op == "gte":
            rule_mask = field_series >= rule.threshold
        elif rule.op == "lte":
            rule_mask = field_series <= rule.threshold
        elif rule.op == "eq":
            rule_mask = field_series == rule.threshold
        elif rule.op == "between":
            if not isinstance(rule.threshold, (list, tuple)) or len(rule.threshold) != 2:
                raise OprimError(f"Threshold for 'between' must be a tuple of 2 floats, got {rule.threshold}")
            rule_mask = field_series.between(rule.threshold[0], rule.threshold[1])
        elif rule.op == "flag":
            rule_mask = field_series == bool(rule.threshold)

        # 记录被此规则剔除的对象 (当前仍存活但将被剔除的)
        newly_rejected = passed_mask & (~rule_mask)
        for _, row in df[newly_rejected].iterrows():
            rejected_list.append({
                "symbol": row["symbol"],
                "failed_rule": rule.field,
                "reason": rule.reason
            })
            
        passed_mask &= rule_mask

    passed_df = df[passed_mask]
    
    return ScreenResult(
        passed=passed_df["symbol"].tolist(),
        rejected=rejected_list,
        stats={
            "total_input": len(df),
            "total_passed": len(passed_df),
            "total_rejected": len(rejected_list)
        }
    )
