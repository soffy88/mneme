"""RCT 实验装配（首个：教学引擎 样例渐退 vs 纯苏格拉底）。

据评审 E3：用 feature-flag 基建跑首个内部 RCT 裁决 L2 默认值。
- 分流：`oprim.experiment.assign_arm` 确定性分臂（无状态、无 migration，臂由 student_id 现算）。
- 主终点：延迟保持率（保留探针，按臂）+ 挫败流失率（行为信号，按臂）。
- **安全默认**：实验 env 关时所有人回 control（教学引擎不开），现网零变化。
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from oprim.experiment import assign_arm
from services.models import InteractionEvent, InteractionSource, User, UserRole

# 挫败流失判据：连续 ≥3 错=挫败一集；末尾仍在挫败集 + 之后 ≥7 天无活动 = 挫败流失
_FRUSTRATION_RUN = 3
_INACTIVE_DAYS = 7


def frustration_dropout_for_student(
    events: list[tuple[bool, datetime]], now: datetime
) -> dict:
    """单学生挫败流失判定（纯函数）。events 按 occurred_at 升序 [(is_correct, occurred_at)]。

    - had_frustration: 出现过 ≥_FRUSTRATION_RUN 连错
    - dropped: 末尾正是连错集（带着挫败离开）且此后 ≥_INACTIVE_DAYS 天无活动
    """
    if not events:
        return {"had_frustration": False, "dropped": False}
    max_run = cur = 0
    for is_c, _ in events:
        cur = cur + 1 if is_c is False else 0
        max_run = max(max_run, cur)
    tail_run = cur  # 循环后 cur = 末尾连错长度
    had = max_run >= _FRUSTRATION_RUN
    last_at = events[-1][1]
    if last_at.tzinfo is None:
        last_at = last_at.replace(tzinfo=timezone.utc)
    inactive = (now - last_at).days >= _INACTIVE_DAYS
    return {
        "had_frustration": had,
        "dropped": had and tail_run >= _FRUSTRATION_RUN and inactive,
    }


# 实验登记表
EXPERIMENTS: dict[str, dict] = {
    "teaching_engine_v1": {
        "arms": ["worked_example", "control"],  # 样例渐退 / 纯苏格拉底(旧行为)
        "ratios": [0.5, 0.5],
        "enabled_env": "EXPERIMENT_TEACHING_ENGINE",  # =1 才分流，否则全 control
        "primary_endpoints": ["delayed_retention", "frustration_dropout"],
    }
}


def student_arm(student_id, experiment: str = "teaching_engine_v1") -> str:
    """学生在该实验的臂。实验未开启(env≠1) → 一律 control（安全默认）。"""
    exp = EXPERIMENTS.get(experiment)
    if not exp:
        return "control"
    if os.environ.get(exp["enabled_env"], "0").lower() not in ("1", "true", "yes"):
        return "control"
    return assign_arm(str(student_id), experiment, exp["arms"], exp["ratios"])


def teaching_engine_on_for(student_id) -> bool:
    """该学生是否启用教学引擎（样例先出）：实验臂=worked_example，或全局 flag 强开。"""
    if os.environ.get("TEACHING_ENGINE_ENABLED", "0").lower() in ("1", "true", "yes"):
        return True
    return student_arm(student_id) == "worked_example"


async def experiment_metrics(
    db: AsyncSession, experiment: str = "teaching_engine_v1"
) -> dict:
    """按臂主终点（聚合无 PII）：延迟保持率(探针) + 挫败流失率(近30天有过 frustrated 行为
    却随后 7 天无活动)。臂由 student_id 现算，故先取全体学生分臂再聚合。"""
    exp = EXPERIMENTS.get(experiment)
    if not exp:
        return {"error": "unknown experiment"}

    # 全体学生 → 臂
    student_ids = [
        r[0]
        for r in (
            await db.execute(
                select(User.id).where(
                    User.role == UserRole.student, User.deleted_at.is_(None)
                )
            )
        ).all()
    ]
    arm_of = {sid: student_arm(sid, experiment) for sid in student_ids}

    # 探针事件（延迟保持）按臂
    probe_rows = (
        await db.execute(
            select(InteractionEvent.student_id, InteractionEvent.is_correct).where(
                InteractionEvent.source == InteractionSource.probe
            )
        )
    ).all()

    # 挫败流失（会话埋点）：近30天真实作答事件，按学生分组排序算挫败集与流失
    now = datetime.now(timezone.utc)
    ev_rows = (
        await db.execute(
            select(
                InteractionEvent.student_id,
                InteractionEvent.is_correct,
                InteractionEvent.occurred_at,
            )
            .where(InteractionEvent.source != InteractionSource.fire_credit)
            .where(InteractionEvent.source != InteractionSource.probe)
            .order_by(InteractionEvent.occurred_at)
        )
    ).all()
    events_by_student: dict = {}
    for sid, is_c, ts in ev_rows:
        events_by_student.setdefault(sid, []).append((is_c, ts))

    per_arm: dict[str, dict] = {
        a: {"n_students": 0, "probe_n": 0, "probe_correct": 0,
            "frustrated_students": 0, "dropped_students": 0}
        for a in exp["arms"]
    }
    for sid, arm in arm_of.items():
        if arm in per_arm:
            per_arm[arm]["n_students"] += 1
            fd = frustration_dropout_for_student(events_by_student.get(sid, []), now)
            if fd["had_frustration"]:
                per_arm[arm]["frustrated_students"] += 1
            if fd["dropped"]:
                per_arm[arm]["dropped_students"] += 1
    for sid, correct in probe_rows:
        parm = arm_of.get(sid)
        if parm is not None and parm in per_arm:
            per_arm[parm]["probe_n"] += 1
            if correct:
                per_arm[parm]["probe_correct"] += 1

    out = {}
    for arm, d in per_arm.items():
        pn = d["probe_n"]
        out[arm] = {
            "n_students": d["n_students"],
            "delayed_retention": round(d["probe_correct"] / pn, 4) if pn else None,
            "delayed_retention_n": pn,
            # 挫败流失率：挫败过的学生里、带着挫败离开且此后无活动的比例（越低越好）
            "frustration_dropout": round(d["dropped_students"] / d["frustrated_students"], 4)
            if d["frustrated_students"] else None,
            "frustrated_students": d["frustrated_students"],
        }
    return {
        "experiment": experiment,
        "enabled": os.environ.get(exp["enabled_env"], "0") in ("1", "true", "yes"),
        "arms": out,
        "note": "延迟保持率(探针)+挫败流失率(会话埋点:连≥3错为挫败,末尾挫败且此后≥7天无活动为流失)按臂聚合。真实裁决需足量样本。",
    }
