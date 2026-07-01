"""
认知状态更新算法（BKT + FSRS 统一更新）
=========================================
3O 范式：oskill/cognitive_state.py

职责：
1. 实现 cognitive_update 纯算法（forgetting-aware BKT + FSRS）。
2. 定义算法输入输出数据结构。
"""

from __future__ import annotations
from datetime import datetime, timezone
from pydantic import BaseModel

from oprim import KCState
from oprim.bkt import bkt_update, classify_error
from oprim.fsrs_engine import (
    fsrs_retrievability, 
    fsrs_review, 
    fsrs_map_rating
)

class CognitiveUpdateInput(BaseModel):
    """认知更新输入。"""
    state: KCState
    card_dict: dict
    is_correct: bool
    used_answer: bool = False
    struggled: bool = False
    effortless: bool = False
    is_interleaved: bool = False
    difficulty: float | None = None   # 题目难度 b∈[0,1]（IRT）；None 时不改变行为
    now: datetime | None = None
    # 集中练习去抖：距上次 FSRS 复习不足该时长(小时)的重复作答视为"集中练习"，
    # 只更新掌握度(BKT)、不推进间隔重复调度，避免同卷连对把卡片排到几天后→遗忘。
    # 默认 0.0：完全不改变行为（逐位等价旧实现），仅调用方显式开启时生效。
    min_review_interval_hours: float = 0.0
    # 个性化 FSRS 权重（按群体/学生从真实复习日志优化）；None → 全局默认（行为不变）。
    fsrs_parameters: tuple | None = None

class CognitiveUpdateResult(BaseModel):
    """认知更新结果。"""
    state: KCState
    card_dict: dict
    error_type: str | None
    rating: str
    rating_val: int
    effective_mastery: float

def _should_advance_schedule(card_dict: dict, now: datetime, min_interval_hours: float) -> bool:
    """是否推进 FSRS 调度。min_interval_hours<=0（默认）恒 True，行为不变。
    新卡片(无 last_review)必推进(首次复习需建立调度)；否则距上次复习≥阈值才推进。"""
    if min_interval_hours <= 0.0:
        return True
    last = card_dict.get("last_review") if isinstance(card_dict, dict) else None
    if not last:
        return True
    try:
        last_dt = datetime.fromisoformat(last) if isinstance(last, str) else last
        if last_dt.tzinfo is None:
            last_dt = last_dt.replace(tzinfo=timezone.utc)
        elapsed_h = (now - last_dt).total_seconds() / 3600.0
        return elapsed_h >= min_interval_hours
    except (ValueError, TypeError):
        return True


def cognitive_update(*, input: CognitiveUpdateInput) -> CognitiveUpdateResult:
    """forgetting-aware BKT + FSRS 统一更新算法（纯函数）。

    Internal oprim composition:
    - oprim.fsrs_retrievability  (算 R)
    - oprim.bkt_update           (forgetting-aware 掌握度更新)
    - oprim.classify_error       (粗心/不会判定)
    - oprim.fsrs_review          (FSRS 卡片更新)
    - oprim.fsrs_map_rating      (表现→Rating)
    
    更新顺序（MUST，与 CLAUDE.md 红线一致）：
    1. 用旧卡片算 R
    2. forgetting-aware BKT 更新（R 衰减先验）
    3. 答错则 classify_error
    4. FSRS review
    """
    now = input.now or datetime.now(timezone.utc)
    fsrs_params = tuple(input.fsrs_parameters) if input.fsrs_parameters else None

    # 1. 算 R (遗忘因子)
    R = fsrs_retrievability(card_dict=input.card_dict, now=now, parameters=fsrs_params)
    
    # 2. BKT 更新 (forgetting-aware + 难度感知)
    bkt_update(state=input.state, is_correct=input.is_correct, retrievability=R, difficulty=input.difficulty)

    # 3. 错误分类
    error_type = None
    if not input.is_correct:
        error_type = classify_error(state=input.state, difficulty=input.difficulty)
        
    # 4. FSRS 更新
    rating = fsrs_map_rating(
        is_correct=input.is_correct, 
        used_answer=input.used_answer,
        struggled=input.struggled, 
        effortless=input.effortless
    )
    if _should_advance_schedule(input.card_dict, now, input.min_review_interval_hours):
        new_card = fsrs_review(card_dict=input.card_dict, rating=rating, now=now, parameters=fsrs_params)
    else:
        # 集中练习去抖：保持原调度（不推进 due/stability），掌握度已在步骤2更新。
        new_card = input.card_dict

    # 5. Recognition 维度更新 (M-G §4.5)：仅交错(混合)情境训练/测量"识别该用哪个 KC"。
    #    交错做对 → 成功识别，p_recognition 上升；交错做错 → 惰性知识，p_recognition 下降。
    #    单 KC 专项(非交错)只提升 mastery、不动 recognition。
    #    独立维度，不触碰已验证的 forgetting-aware BKT / FSRS（p_mastery 路径不变）。
    if input.is_interleaved:
        pr = input.state.p_recognition
        if pr is None:
            pr = input.state.p_recognition_init or 0.20
        pt = input.state.p_transit
        if input.is_correct:
            pr = pr + (1.0 - pr) * pt
        else:
            pr = pr * (1.0 - pt)
        input.state.p_recognition = max(0.001, min(0.97, pr))  # 与 mastery 同封顶 0.97

    input.state.last_interaction_ts = now.timestamp()
    
    eff = (input.state.long_term_mastery or input.state.current()) * R
    
    return CognitiveUpdateResult(
        state=input.state,
        card_dict=new_card,
        error_type=error_type,
        rating=rating.name,
        rating_val=rating.value,
        effective_mastery=eff
    )

__version__ = "0.3.0"
__manifest__ = {
    "version": __version__,
    "updated_at": "2026-06-13",
    "elements": [
        {"name": "cognitive_update", "layer": "oskill", "summary": "BKT+FSRS 统一更新算法"},
    ]
}
