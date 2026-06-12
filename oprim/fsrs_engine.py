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
from fsrs import Scheduler, Card, Rating

# 全局调度器（可后续按学生加载个性化参数）
_scheduler = Scheduler()


def fsrs_new_card() -> dict:
    """新建一张记忆卡片，返回可入库的 dict。"""
    return Card().to_dict()


def fsrs_map_rating(
    *,
    is_correct: bool,
    used_answer: bool = False,      # 是否看了答案/直接放弃
    struggled: bool = False,        # 是否很吃力/超时
    effortless: bool = False,       # 是否一眼秒杀
) -> Rating:
    """学生表现 → FSRS Rating（Again/Hard/Good/Easy）。"""
    if used_answer or not is_correct:
        return Rating.Again
    if struggled:
        return Rating.Hard
    if effortless:
        return Rating.Easy
    return Rating.Good


def fsrs_review(
    *,
    card_dict: dict,
    rating: Rating,
    now: datetime | None = None
) -> dict:
    """对一张卡片做一次复习，返回更新后的 card dict。"""
    card = Card.from_dict(card_dict)
    now = now or datetime.now(timezone.utc)
    card, _log = _scheduler.review_card(card, rating, review_datetime=now)
    return card.to_dict()


def fsrs_retrievability(
    *,
    card_dict: dict,
    now: datetime | None = None
) -> float:
    """当前可提取性 R (0~1)：此刻能回忆起的概率。"""
    card = Card.from_dict(card_dict)
    now = now or datetime.now(timezone.utc)

    # 优先用官方方法
    for meth in ("get_card_retrievability", "retrievability"):
        fn = getattr(_scheduler, meth, None) or getattr(card, meth, None)
        if callable(fn):
            try:
                # py-fsrs 5.x+
                if fn.__self__ is _scheduler:
                    return float(fn(card, now))
                else:
                    return float(fn(now))
            except Exception:
                pass

    # 兜底：用 FSRS 公式自行计算
    S = getattr(card, "stability", None)
    last = getattr(card, "last_review", None)
    if not S or last is None:
        return 1.0
    t_days = max(0.0, (now - last).total_seconds() / 86400.0)
    # FSRS v4 formula constant
    DECAY = -0.5
    FACTOR = 0.9 ** (1 / DECAY) - 1
    return (1 + FACTOR * t_days / S) ** DECAY


def fsrs_due_date(*, card_dict: dict) -> str | None:
    """返回下次复习日期 ISO 字符串，新卡片返回 None。"""
    card = Card.from_dict(card_dict)
    return card.due.isoformat() if card.due else None

__version__ = "0.1.0"
__manifest__ = {
    "version": __version__,
    "updated_at": "2026-06-12",
    "elements": [
        {"name": "fsrs_new_card", "layer": "oprim", "summary": "创建新 FSRS 记忆卡片"},
        {"name": "fsrs_review", "layer": "oprim", "summary": "复习卡片更新"},
        {"name": "fsrs_retrievability", "layer": "oprim", "summary": "计算当前可提取性 R"},
        {"name": "fsrs_map_rating", "layer": "oprim", "summary": "表现映射为 Rating"},
        {"name": "fsrs_due_date", "layer": "oprim", "summary": "返回下次复习日期"},
    ]
}
