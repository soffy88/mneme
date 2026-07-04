"""L1 · 统一学习者模型（单一真相源）。

架构重排 P0：所有上层功能对"掌握 / 学习阶段 / 难度带 / 掌握色"**只读本模块**，
不得再私自定阈值（此前 fringe=0.6、mastery_color 绿=0.75、成就/联赛=0.7 各定各的）。
四算法唯一职责：IRT 标定 θ / BKT 出 KU 掌握 / FSRS 保持调度 / FIRe 前置信用——本模块
是它们对上层的**读门面**，不改任一算法契约。
"""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from oprim.prereq_graph import fringe_status
from services.models import KCMastery

# ── 权威阈值（单源，散落字面量一律迁移引用此处）─────────────────────────────
GATE = 0.6  # 前置放行 / 薄弱线（低于=薄弱、前置未达此值=锁）
MASTERED = 0.7  # 掌握裁决：计数、进入巩固态
GREEN = 0.75  # 掌握色：绿
YELLOW = 0.40  # 掌握色：黄
_NASCENT = 0.05  # 视为"未开始"


def mastery_color(p: Optional[float]) -> str:
    """掌握色（单源）。"""
    if p is None:
        return "unknown"
    if p >= GREEN:
        return "green"
    if p >= YELLOW:
        return "yellow"
    return "red"


def fringe(
    p_mastery: Optional[float],
    prerequisites: Optional[list[str]],
    mastery_map: dict[str, Optional[float]],
) -> str:
    """KST fringe（掌握门控），阈值统一取 GATE。见 oprim.prereq_graph.fringe_status。"""
    return fringe_status(p_mastery, prerequisites, mastery_map, threshold=GATE)


def get_stage(
    p_mastery: Optional[float],
    *,
    prereqs_ok: bool = True,
) -> str:
    """L2 学习阶段状态机（每 KU）：worked_example→completion→retrieval→consolidation。

    - ``worked_example`` 未开始（前置齐才可学）：给完整样例 + 自我解释
    - ``completion``     在学中（<GATE）：补全题（faded worked examples）
    - ``retrieval``      半熟（GATE~MASTERED）：独立检索
    - ``consolidation``  已掌握（≥MASTERED）：交错混合复习
    前置未齐 → locked（不进状态机，先补前置）。
    """
    pm = p_mastery
    if pm is not None and pm >= MASTERED:
        return "consolidation"
    if pm is not None and pm >= GATE:
        return "retrieval"
    if pm is not None and pm > _NASCENT:
        return "completion"
    # 未开始
    return "worked_example" if prereqs_ok else "locked"


def get_zpd_band(p_mastery: Optional[float], theta: Optional[float] = None) -> dict:
    """最近发展区难度带：维持 70–85% 成功率。

    优先用 IRT 能力 θ（L3 estimate_ability 估出）为中心（θ 是能力的直接度量）；
    无 θ 时退回按掌握度就近取带（启发式）。返回目标题目难度区间 difficulty∈[0,1]。
    目标略高于能力以维持理想难度：中心上移 +0.05（70–85% 成功带的下沿）。
    """
    center = (
        theta if theta is not None else (p_mastery if p_mastery is not None else 0.5)
    )
    center = min(max(center + 0.05, 0.0), 1.0)  # 略高于当前能力=理想难度
    lo = max(0.0, center - 0.10)
    hi = min(1.0, center + 0.15)
    return {
        "difficulty_min": round(lo, 3),
        "difficulty_max": round(hi, 3),
        "target_success": [0.70, 0.85],
        "source": "theta" if theta is not None else "mastery",
    }


async def get_mastery(db: AsyncSession, student_id: UUID, ku_id: str) -> dict:
    """单 KU 掌握读门面：{p, evidence_n, started, mastery_confirmed}。上层只读这里，不自算。

    mastery_confirmed（U.17）是独立于 p（BKT 持续估计）的裁决状态，只由
    mastery_gate_service 的隔离裁决题判定写入，不随日常练习/复习自动变化。
    """
    row = (
        await db.execute(
            select(
                KCMastery.p_mastery, KCMastery.n_attempts, KCMastery.mastery_confirmed
            ).where(
                KCMastery.student_id == student_id,
                KCMastery.knowledge_point == ku_id,
            )
        )
    ).first()
    if row is None:
        return {
            "p": None,
            "evidence_n": 0,
            "started": False,
            "mastery_confirmed": False,
        }
    p, n, confirmed = row
    return {
        "p": p,
        "evidence_n": int(n or 0),
        "started": True,
        "mastery_confirmed": bool(confirmed),
    }
