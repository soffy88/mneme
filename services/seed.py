"""
services/seed.py — 启动时 BKT 先验参数种子填充（幂等）
"""
from __future__ import annotations

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from data.guangdong_math_kc import KC_LIST
from services.models import BKTPrior

_GUESS_RATES = {"choice": 0.25, "fill": 0.05, "solve": 0.02}


async def seed_bkt_priors(db: AsyncSession) -> int:
    """Upsert KC × 题型 先验参数到 bkt_priors 表，返回 upsert 行数。"""
    rows = []
    for kc in KC_LIST:
        bkt = kc["bkt"]
        for q_type in kc.get("question_types", ["solve"]):
            rows.append(
                {
                    "subject": "math",
                    "grade": kc["grade"],
                    "knowledge_point": kc["kc_id"],
                    "question_type": q_type,
                    "p_init": bkt["p_init"],
                    "p_transit": bkt["p_transit"],
                    "p_guess": _GUESS_RATES.get(q_type, bkt["p_guess"]),
                    "p_slip": bkt["p_slip"],
                }
            )

    if not rows:
        return 0

    stmt = (
        pg_insert(BKTPrior)
        .values(rows)
        .on_conflict_do_update(
            constraint="uq_bkt_priors_kc_qtype",
            set_={
                "p_init": pg_insert(BKTPrior).excluded.p_init,
                "p_transit": pg_insert(BKTPrior).excluded.p_transit,
                "p_guess": pg_insert(BKTPrior).excluded.p_guess,
                "p_slip": pg_insert(BKTPrior).excluded.p_slip,
            },
        )
    )
    await db.execute(stmt)
    return len(rows)
