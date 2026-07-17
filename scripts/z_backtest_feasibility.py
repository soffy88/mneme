"""S4 — Z 回测数据可行性普查（一次性/可重跑，非 CI 内跑）。

Z=0.84（`mneme_core.oprim.mastery_gate.Z`）是量化 KC 过门的置信下界 z 分数
（`p_learned - Z*sigma >= threshold`），目前只在合成数据上验证过判别力
（scripts/moat_eval/，AUC 0.677 ≥ 0.65 合成门槛；见其 README "已知局限 1：
合成 ≠ 真实"）。真实数据回测（检验 Z=0.84 对应的置信下界是否真达到约 80%
校准覆盖率）需要足量真实 (student, KC) 观测对，本脚本只做**可行性普查**：
数够不够跑，不做真跑。

判据：沿用 mastery_gate 自己的口径——`kc_mastery.n_attempts >= N_MIN`
（Z 置信下界只在 N_MIN 已达标的 (student,KC) 对上才会被 gate 实际用到，
用同一门槛统计"够不够格回测"最贴合真实使用面）。

决策规则（S4 拍定）：合格对 < 200 → 不跑真实回测，只记录当前值，推迟到真实
数据量上来（用户外部跟踪为 W4）；Z=0.84 本身不改、不放宽。

    docker compose exec api python scripts/z_backtest_feasibility.py
"""

from __future__ import annotations

import asyncio

import asyncpg

from mneme_core.oprim.mastery_gate import N_MIN, Z
from obase.config import settings

FEASIBILITY_THRESHOLD = 200

_QUERY = """
    SELECT count(*) FILTER (WHERE n_attempts >= $1) AS qualified_pairs,
           count(*) AS total_pairs,
           count(DISTINCT student_id) AS distinct_students
    FROM kc_mastery
"""


async def run() -> None:
    conn = await asyncpg.connect(settings.DATABASE_URL.replace("+asyncpg", ""))
    try:
        row = await conn.fetchrow(_QUERY, N_MIN)
    finally:
        await conn.close()

    qualified = row["qualified_pairs"]
    print(f"Z（当前值，不改）        = {Z}")
    print(f"N_MIN（合格判据）        = {N_MIN}")
    print(f"kc_mastery 总行数        = {row['total_pairs']}")
    print(f"distinct 学生数          = {row['distinct_students']}")
    print(f"合格 (student,KC) 对     = {qualified}")
    print(f"可行性门槛               = {FEASIBILITY_THRESHOLD}")

    if qualified < FEASIBILITY_THRESHOLD:
        print(
            f"结论：{qualified} < {FEASIBILITY_THRESHOLD}，数据不足以支撑有统计意义的"
            "真实回测。不跑真实回测，只记录当前值，推迟（W4）。Z=0.84 不改、不放宽。"
        )
    else:
        print(
            f"结论：{qualified} >= {FEASIBILITY_THRESHOLD}，数据量已够格，可设计真实"
            "回测（校验置信下界实际覆盖率）——不在本脚本范围内。"
        )


if __name__ == "__main__":
    asyncio.run(run())
