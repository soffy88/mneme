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

from functools import lru_cache

# 全局调度器（默认 FSRS-6 权重）
_scheduler = Scheduler()


@lru_cache(maxsize=64)
def _scheduler_for(parameters: tuple | None) -> Scheduler:
    """按权重向量取（缓存的）Scheduler。parameters=None → 全局默认（行为不变）。

    个性化基础设施：调用方可传按学生/群体优化出的 FSRS 权重，移除"只有一个
    全局默认 Scheduler"的架构瓶颈。权重的拟合/选择见 services.fsrs_optimize_service。
    """
    if not parameters:
        return _scheduler
    return Scheduler(parameters=parameters)


# fsrs_new_card（初始卡片工厂）归 obase.cognitive_types（单源），此处 re-export 保持兼容。
from obase.cognitive_types import fsrs_new_card  # noqa: E402,F401


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
    now: datetime | None = None,
    parameters: tuple | None = None,
) -> dict:
    """对一张卡片做一次复习，返回更新后的 card dict。

    parameters：可选的个性化 FSRS 权重；None → 全局默认（行为不变）。
    """
    card = Card.from_dict(card_dict)
    now = now or datetime.now(timezone.utc)
    scheduler = _scheduler_for(parameters)
    card, _log = scheduler.review_card(card, rating, review_datetime=now)
    return card.to_dict()


def fsrs_retrievability(
    *,
    card_dict: dict,
    now: datetime | None = None,
    parameters: tuple | None = None,
) -> float:
    """当前可提取性 R (0~1)：此刻能回忆起的概率。

    parameters：可选的个性化 FSRS 权重；None → 全局默认（行为不变）。
    """
    card = Card.from_dict(card_dict)

    # 核心修正：对于从未复习过的新卡片，可提取性视为 1.0 (BKT 初始掌握度不衰减)
    if card.last_review is None:
        return 1.0

    now = now or datetime.now(timezone.utc)
    scheduler = _scheduler_for(parameters)

    # 优先用官方方法
    for meth in ("get_card_retrievability", "retrievability"):
        fn = getattr(scheduler, meth, None) or getattr(card, meth, None)
        if callable(fn):
            try:
                # py-fsrs 5.x+：scheduler 方法签名 (card, now)，card 方法签名 (now)
                if getattr(fn, "__self__", None) is scheduler:
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
