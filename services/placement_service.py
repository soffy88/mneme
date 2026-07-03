"""L3 · 自适应定位会话（CAT 驱动器，无状态）。

入学/冷启动诊断：每轮把累积 (KU难度,对错) 交给 Rasch 估 θ，SE<阈值或达题数上限即停，
否则从该科目 KU 池选难度就近 θ 的下一题。客户端累积响应，服务端无会话状态（可复现、易测）。
"""

from __future__ import annotations


from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from oprim.ability import estimate_ability, next_item_difficulty
from services.learner_model import get_zpd_band
from services.models import KnowledgeUnit, Textbook

_DEFAULT_MAX_ITEMS = 25
_DEFAULT_SE = 0.10  # SE(θ) 低于此值停止（约 20–35 题量级）


async def cat_next(
    db: AsyncSession,
    *,
    subject: str,
    responses: list[dict],
    served_ku_ids: list[str],
    max_items: int = _DEFAULT_MAX_ITEMS,
    se_threshold: float = _DEFAULT_SE,
) -> dict:
    """CAT 一步：估 θ → 判停 → 选下一题。

    responses: [{difficulty, is_correct}]（累积）；served_ku_ids: 已发过的 KU（去重）。
    返回 {done, theta, se, n, next_ku|None, weak_ku_ids?(停时)}。
    """
    est = estimate_ability(
        [(float(r["difficulty"]), bool(r["is_correct"])) for r in responses]
    )
    theta, se, n = est["theta"], est["se"], est["n"]

    done = n >= max_items or (se is not None and se < se_threshold)
    if done:
        # 定位结束：答错的题（难度 < θ 却错，或整体薄弱）供后续初始化冷启动薄弱清单
        return {
            "done": True,
            "theta": theta,
            "se": se,
            "n": n,
            "zpd_band": get_zpd_band(None, theta=theta),
            "recommended_start_difficulty": next_item_difficulty(theta),
            "next_ku": None,
        }

    # 选下一题：该科目、难度就近 θ、未发过、可放的 KU
    target = next_item_difficulty(theta)
    stmt = (
        select(KnowledgeUnit.id, KnowledgeUnit.name, KnowledgeUnit.difficulty)
        .join(Textbook, KnowledgeUnit.textbook_id == Textbook.id)
        .where(Textbook.subject == subject)
    )
    if served_ku_ids:
        stmt = stmt.where(KnowledgeUnit.id.not_in(served_ku_ids))
    rows = (await db.execute(stmt)).all()
    if not rows:
        # 无更多题：提前结束
        return {
            "done": True,
            "theta": theta,
            "se": se,
            "n": n,
            "next_ku": None,
            "note": "题库不足，提前结束定位",
        }

    # 难度离 target 最近者（平手取 id 稳定）
    best = min(rows, key=lambda r: (abs((r[2] or 0.5) - target), r[0]))
    return {
        "done": False,
        "theta": theta,
        "se": se,
        "n": n,
        "next_ku": {
            "id": best[0],
            "name": best[1],
            "difficulty": round(best[2] or 0.5, 3),
        },
    }
