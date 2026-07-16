"""progress_assembler — 把 mneme 真相源投影成 mneme-core 的 LearningProgress。

架构 A：mneme app 侧组装（有 DB），产物喂给纯库 mneme-core 的
`is_mastered`/`next_objective`/`map_summary`（它们只认 LearningProgress，不碰 IO）。

gate_type 由 rubric 存在性决定（决策 D2.2 净规则，经 gate_store）：
    有 rubric → kp.type=CONCEPT（定性，读 gate.qualitative_mastery）
    无 rubric → kp.type=PROCEDURE（量化，读 kc_mastery 下界过门）
导出量（SPEC §4）：n_obs = interaction_events 计数；sigma = 二项近似 sqrt(p(1-p)/n_obs)。
只读投影，绝不改既有表（铁律）。

依赖 mneme_core 可 import（②-0 打包：现经 PYTHONPATH，落地时装进镜像）。
"""

from __future__ import annotations

import math
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from mneme_core.oprim.mastery_gate import N_MIN, QUANTITATIVE_GATE, Z
from mneme_core.oprim.mastery_lower_bound import mastery_lower_bound
from mneme_core.oprim.models import (
    BktPosterior,
    FsrsState,
    KnowledgePoint,
    KnowledgeType,
    LearningProgress,
    Module,
    PendingQuestion,
    ReviewTask,
)

from services import gate_store
from services.models import InteractionEvent, KCMastery, KnowledgeUnit


def _sigma(p: float, n_obs: int) -> float:
    """二项近似后验标准差；无观测则给较宽的 0.5（is_mastered 另有 n_obs<N_MIN 闸）。"""
    if n_obs <= 0:
        return 0.5
    return math.sqrt(max(p * (1.0 - p), 0.0) / n_obs)


def _due_unix(fsrs_json: Optional[dict]) -> Optional[float]:
    """从 fsrs_card_json['due']（ISO 或 datetime）取 unix 秒；无/非法 → None。"""
    if not fsrs_json:
        return None
    due = fsrs_json.get("due")
    if not due:
        return None
    if hasattr(due, "timestamp"):
        return due.timestamp()
    try:
        return datetime.fromisoformat(str(due).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


async def build_learning_progress(
    db: AsyncSession, student_id: uuid.UUID, kc_ids: list[str]
) -> LearningProgress:
    """把给定路径 kc_ids 的真实掌握度/复习/定性状态投影成 LearningProgress。"""
    # KC 名称（knowledge_units）
    name_rows = (
        await db.execute(
            select(KnowledgeUnit.id, KnowledgeUnit.name).where(
                KnowledgeUnit.id.in_(kc_ids)
            )
        )
    ).all()
    names = {r.id: r.name for r in name_rows}

    # 该学生这些 KC 的 kc_mastery
    mastery_rows = (
        (
            await db.execute(
                select(KCMastery).where(
                    KCMastery.student_id == student_id,
                    KCMastery.knowledge_point.in_(kc_ids),
                )
            )
        )
        .scalars()
        .all()
    )
    mastery_by_kc = {m.knowledge_point: m for m in mastery_rows}

    qual_map = await gate_store.get_qualitative_mastery_map(db, student_id)

    bkt: dict[str, BktPosterior] = {}
    fsrs: dict[str, FsrsState] = {}
    review_queue: list[ReviewTask] = []
    kps: list[KnowledgePoint] = []

    for kc in kc_ids:
        gate_type = await gate_store.resolve_gate_type(db, kc)
        ktype = (
            KnowledgeType.CONCEPT
            if gate_type == gate_store.QUALITATIVE
            else KnowledgeType.PROCEDURE
        )
        kps.append(KnowledgePoint(id=kc, name=names.get(kc, kc), type=ktype))

        m = mastery_by_kc.get(kc)
        if m is None or m.p_mastery is None:
            continue

        n_obs = (
            await db.execute(
                select(func.count())
                .select_from(InteractionEvent)
                .where(
                    InteractionEvent.student_id == student_id,
                    InteractionEvent.knowledge_point == kc,
                )
            )
        ).scalar_one()
        p = float(m.p_mastery)
        bkt[kc] = BktPosterior(
            p_learned=p, sigma=_sigma(p, int(n_obs)), n_obs=int(n_obs)
        )

        due = _due_unix(m.fsrs_card_json)
        if due is not None:
            fsrs[kc] = FsrsState(
                stability=0.0, difficulty=0.0, last_review=0.0, due_at=due, reps=0
            )
            # error-linked 提权（V11 / SPEC §4）：该 student×KC 有错误史且尚未 graduated
            # → priority=1，否则 priority=2。只读既有 interaction_events，不改其 schema。
            # graduated 判据：量化=下界过门（复用 mastery_lower_bound 元素）；定性=gate flag。
            error_count = (
                await db.execute(
                    select(func.count())
                    .select_from(InteractionEvent)
                    .where(
                        InteractionEvent.student_id == student_id,
                        InteractionEvent.knowledge_point == kc,
                        InteractionEvent.is_correct.is_(False),
                    )
                )
            ).scalar_one()
            if gate_type == gate_store.QUALITATIVE:
                graduated = qual_map.get(kc, False)
            else:
                threshold = QUANTITATIVE_GATE.get(KnowledgeType.PROCEDURE, 0.9)
                graduated = (
                    bkt[kc].n_obs >= N_MIN
                    and mastery_lower_bound(p, sigma=bkt[kc].sigma, z=Z) >= threshold
                )
            priority = 1 if (int(error_count) > 0 and not graduated) else 2
            review_queue.append(
                ReviewTask(knowledge_point_id=kc, due_at=due, priority=priority)
            )

    module = Module(id="path", name="学习路径", order=0, knowledge_points=kps)

    # 待答题（gate.pending_question）→ 驱动 next_objective 的 ANSWER_PENDING 优先级。
    # expected 载于内存 progress 供服务层判分，路由序列化时**绝不外传**（红线）。
    pending = await gate_store.get_active_pending(db, student_id=student_id)
    pending_question = (
        PendingQuestion(
            knowledge_point_id=pending["kc_id"],
            module_id=module.id,
            prompt=pending["prompt"],
            expected=pending["expected"] or "",
            qtype=pending["qtype"],
            question_id=pending["question_id"],
        )
        if pending is not None
        else None
    )

    return LearningProgress(
        student_id=str(student_id),
        modules=[module],
        bkt=bkt,
        qualitative_mastery=dict(qual_map),
        fsrs=fsrs,
        review_queue=review_queue,
        pending_question=pending_question,
    )
