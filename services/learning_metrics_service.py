"""L0 · 学习层北极星指标（飞轮换宪法）。

模型层(AUC/校准 RMSE)与产品层(留存)降为从属；一级指标改为**学习层四指标**：
掌握速度 / 延迟保持率 / 迁移率 / 校准度。聚合、无 PII。红线：留存涨而学习平 = 回滚。
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from services.learner_model import MASTERED
from services.models import InteractionEvent, InteractionSource, KCMastery


async def compute_learning_metrics(db: AsyncSession) -> dict:
    """全体学习层四指标（cohort 聚合，无 PII）。缺数据的指标返回 None + 说明。"""

    # 排除 fire_credit 记账事件（非真实作答）
    real = InteractionEvent.source != InteractionSource.fire_credit

    # ── 掌握速度：已掌握 KU 数 / 有效学习小时 ──────────────────────────────
    mastered_ku = (
        await db.execute(
            select(func.count())
            .select_from(KCMastery)
            .where(KCMastery.p_mastery >= MASTERED)
        )
    ).scalar() or 0
    total_secs = (
        await db.execute(
            select(
                func.coalesce(func.sum(InteractionEvent.time_spent_seconds), 0)
            ).where(real)
        )
    ).scalar() or 0
    study_hours = float(total_secs) / 3600.0
    mastery_speed = round(mastered_ku / study_hours, 4) if study_hours > 0 else None

    # ── 延迟保持率：保留探针(远未到期卡)实测正确率 ─────────────────────────
    probe_rows = (
        await db.execute(
            select(InteractionEvent.is_correct).where(
                InteractionEvent.source == InteractionSource.probe
            )
        )
    ).all()
    n_probe = len(probe_rows)
    delayed_retention = (
        round(sum(1 for (c,) in probe_rows if c) / n_probe, 4) if n_probe else None
    )

    # ── 校准度：JOL 预测把握 vs 实际正确（overconfidence = 均预测 − 均正确）──
    jol_rows = (
        await db.execute(
            select(
                InteractionEvent.predicted_confidence, InteractionEvent.is_correct
            ).where(InteractionEvent.predicted_confidence.is_not(None), real)
        )
    ).all()
    n_jol = len(jol_rows)
    if n_jol:
        mean_pred = sum(float(p) for p, _ in jol_rows) / n_jol
        mean_acc = sum(1 for _, c in jol_rows if c) / n_jol
        overconfidence = round(mean_pred - mean_acc, 4)
    else:
        overconfidence = None

    # ── 迁移率：迁移探针(U.18，现场生成不落库，同 KU 新实例)实测正确率 ──────────
    transfer_rows = (
        await db.execute(
            select(InteractionEvent.is_correct).where(
                InteractionEvent.source == InteractionSource.transfer_probe
            )
        )
    ).all()
    n_transfer = len(transfer_rows)
    transfer_rate = (
        round(sum(1 for (c,) in transfer_rows if c) / n_transfer, 4)
        if n_transfer
        else None
    )

    return {
        "mastery_speed": mastery_speed,  # 已掌握 KU / 学习小时
        "mastery_speed_detail": {
            "mastered_ku": int(mastered_ku),
            "study_hours": round(study_hours, 2),
        },
        "delayed_retention": delayed_retention,  # 探针实测召回率
        "delayed_retention_n": n_probe,
        "calibration_overconfidence": overconfidence,  # >0=高估, 目标趋 0
        "calibration_n": n_jol,
        "transfer_rate": transfer_rate,  # 迁移探针实测正确率
        "transfer_rate_n": n_transfer,
        "transfer_note": (
            "U.18：现场生成同 KU 新实例变式（near transfer），非跨 KU/新情境的"
            "远迁移（far transfer）；真远迁移题池需教研设计，暂未建"
        ),
    }


async def compute_for_student(db: AsyncSession, student_id) -> Optional[dict]:
    """预留：单学生学习层指标（当前用全体聚合，个体版待更多数据）。"""
    return None
