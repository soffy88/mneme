"""
FSRS 间隔重复引擎封装
=====================
基于官方 py-fsrs 库（Anki 默认算法 FSRS）。替代 v1.2 的 SM-2。

职责：
- 为每道错题/记忆项维护 FSRS Card（难度D/稳定性S/可提取性R）
- 把学生回顾表现映射为 FSRS 的 Rating（Again/Hard/Good/Easy）
- 计算当前可提取性 R（供 BKT 的 forgetting-aware 衰减使用）
- 调度下次复习时间 due
"""

from __future__ import annotations
from datetime import datetime, timezone
from typing import Optional
import math

from fsrs import Scheduler, Card, Rating

# 全局调度器（可后续按学生加载个性化参数）
_scheduler = Scheduler()


def new_card() -> dict:
    """新建一张记忆卡片，返回可入库的 dict。"""
    return Card().to_dict()


# ---- 学生表现 → FSRS Rating 映射 ----
# 适用于试卷错题/快速录入/苏格拉底/回顾等多种来源的统一映射。
def map_performance_to_rating(
    is_correct: bool,
    *,
    used_answer: bool = False,      # 是否看了答案/直接放弃
    struggled: bool = False,        # 是否很吃力/超时
    effortless: bool = False,       # 是否一眼秒杀
) -> Rating:
    if used_answer or not is_correct:
        return Rating.Again
    if struggled:
        return Rating.Hard
    if effortless:
        return Rating.Easy
    return Rating.Good


def review(card_dict: dict, rating: Rating,
           now: Optional[datetime] = None) -> dict:
    """对一张卡片做一次复习，返回更新后的 card dict。"""
    card = Card.from_dict(card_dict)
    now = now or datetime.now(timezone.utc)
    card, _log = _scheduler.review_card(card, rating, review_datetime=now)
    return card.to_dict()


def retrievability(card_dict: dict, now: Optional[datetime] = None) -> float:
    """当前可提取性 R (0~1)：此刻能回忆起的概率。
    用 FSRS 的记忆模型：R = (1 + FACTOR * t / S) ** DECAY
    若库提供了 get_card_retrievability 则优先用官方实现。
    """
    card = Card.from_dict(card_dict)
    now = now or datetime.now(timezone.utc)

    # 优先用官方方法（不同版本方法名可能不同，做兼容）
    for meth in ("get_card_retrievability", "retrievability"):
        fn = getattr(_scheduler, meth, None) or getattr(card, meth, None)
        if callable(fn):
            try:
                return float(fn(card, now)) if fn.__self__ is _scheduler else float(fn(now))
            except Exception:
                pass

    # 兜底：用 FSRS 公式自行计算
    S = getattr(card, "stability", None)
    last = getattr(card, "last_review", None)
    if not S or last is None:
        return 1.0
    t_days = max(0.0, (now - last).total_seconds() / 86400.0)
    DECAY = -0.5
    FACTOR = 0.9 ** (1 / DECAY) - 1
    return (1 + FACTOR * t_days / S) ** DECAY


def due_date(card_dict: dict) -> Optional[str]:
    card = Card.from_dict(card_dict)
    return card.due.isoformat() if card.due else None
