"""学习洞察 / 校准 / 摸底 / 护城河指标（自 main 拆出）。"""
from __future__ import annotations

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from obase.db import get_db
from oprim.calibration import brier_calibration
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.auth_deps import get_current_user, require_student_access
from services.cognitive_service import (
    weakness_roots,
    weekly_digest,
)
from services.models import (
    EffortfulGain,
    EvaluationRun,
    InteractionEvent,
    KnowledgeUnit,
    Textbook,
    User,
    WrongQuestion,
)
from services.placement_service import cat_next

router = APIRouter(tags=["insights"])

# ===== §F.0 努力收益看板（M-F）=====


@router.get("/v1/effortful-gains/{student_id}")
async def get_effortful_gains(
    student_id: UUID,
    limit: int = Query(10, ge=1, le=50),
    _auth: User = Depends(require_student_access),
    db: AsyncSession = Depends(get_db),
):
    """GET /v1/effortful-gains/{student_id} — 努力收益看板（M-F）。
    展示"做得吃力、但记忆稳定性提升最多"的题，按 effortful_gain 降序。
    """
    rows = (
        (
            await db.execute(
                select(EffortfulGain)
                .where(EffortfulGain.student_id == student_id)
                .order_by(EffortfulGain.effortful_gain.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )

    qids = [r.question_id for r in rows if r.question_id]
    kc_map: dict = {}
    if qids:
        wqs = (
            await db.execute(
                select(WrongQuestion.id, WrongQuestion.knowledge_points).where(
                    WrongQuestion.id.in_(qids)
                )
            )
        ).all()
        for qid, kps in wqs:
            kc_map[qid] = next(iter((kps or {}).values()), None)

    return {
        "top_gains": [
            {
                "question_id": str(r.question_id) if r.question_id else None,
                "kc": kc_map.get(r.question_id),
                "struggle_score": r.struggle_score,
                "retention_delta": r.retention_delta,
                "effortful_gain": r.effortful_gain,
                "occurred_at": r.occurred_at.isoformat() if r.occurred_at else None,
            }
            for r in rows
        ]
    }


@router.get("/v1/weak-roots/{student_id}")
async def get_weak_roots(
    student_id: UUID,
    _auth: User = Depends(require_student_access),
    db: AsyncSession = Depends(get_db),
):
    """GET /v1/weak-roots/{student_id} — 前置图谱归因。
    对薄弱知识点上溯前置链，找出"先补根再补叶"的薄弱/未练前置。
    """

    return {"roots": await weakness_roots(db, student_id)}


@router.get("/v1/weekly-digest/{student_id}")
async def get_weekly_digest(
    student_id: UUID,
    _auth: User = Depends(require_student_access),
    db: AsyncSession = Depends(get_db),
):
    """GET /v1/weekly-digest/{student_id} — 留存引擎：连续天数 + 本周成长摘要。"""

    return await weekly_digest(db, student_id)


@router.get("/v1/parent/report/{student_id}")
async def get_parent_report(
    student_id: UUID,
    date: date | None = Query(None),
    _auth: User = Depends(require_student_access),
    db: AsyncSession = Depends(get_db),
):
    """GET /v1/parent/report/{student_id}?date — 家长学习日报（可转发微信）。"""
    from services.cognitive_service import daily_report

    return await daily_report(db, student_id, date)


@router.get("/v1/calibration/{student_id}")
async def get_calibration(
    student_id: UUID,
    _auth: User = Depends(require_student_access),
    db: AsyncSession = Depends(get_db),
):
    """GET /v1/calibration/{student_id} — JOL 校准（判断学习的准度）。
    比较作答前自评把握(predicted_confidence)与实际对错：
    brier 越低越准；overconfidence>0=高估自己(努力错觉)，<0=低估自己。
    """
    rows = (
        await db.execute(
            select(InteractionEvent.predicted_confidence, InteractionEvent.is_correct)
            .where(InteractionEvent.student_id == student_id)
            .where(InteractionEvent.predicted_confidence.is_not(None))
        )
    ).all()
    return brier_calibration(
        predicted=[float(p) for p, _ in rows],
        actual=[1.0 if c else 0.0 for _, c in rows],
    )


@router.get("/v1/moat/evaluation-history")
async def get_evaluation_history(
    limit: int = Query(52, ge=1, le=520),
    _auth: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """GET /v1/moat/evaluation-history — 护城河实证历史（周评估 AUC/log-loss 落表）。
    登录即可读（模型质量是全体聚合数据，无个人信息）；按 ran_at 倒序。
    """
    rows = (
        (
            await db.execute(
                select(EvaluationRun).order_by(EvaluationRun.ran_at.desc()).limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return {
        "runs": [
            {
                "id": str(r.id),
                "ran_at": r.ran_at.isoformat() if r.ran_at else None,
                "window_start": r.window_start.isoformat() if r.window_start else None,
                "window_end": r.window_end.isoformat() if r.window_end else None,
                "n_events": r.n_events,
                "n_students": r.n_students,
                "auc": round(r.auc, 4) if r.auc is not None else None,
                "log_loss": round(r.log_loss, 4) if r.log_loss is not None else None,
                "meta": r.meta,
            }
            for r in rows
        ]
    }


@router.get("/v1/moat/retention-metrics")
async def get_retention_metrics(
    _auth: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """GET /v1/moat/retention-metrics — 留存三指标（T.2）。

    D7 留存 / 到期复习完成率 / 保留探针校准（实测召回 vs FSRS 预测 R）。
    登录即可读（全体聚合数据，无个人信息）；口径见 services.retention_service。
    """
    from services.retention_service import retention_metrics

    return await retention_metrics(db)


@router.get("/v1/moat/learning-metrics")
async def get_learning_metrics(
    _auth: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """GET /v1/moat/learning-metrics — L0 学习层北极星四指标（架构重排）。

    掌握速度 / 延迟保持率(探针升格) / 迁移率 / 校准度。**一级指标**——模型层(AUC)与
    产品层(留存)降为从属。登录可读，全体聚合无 PII。红线：留存涨而学习平 = 回滚。
    """
    from services.learning_metrics_service import compute_learning_metrics

    return await compute_learning_metrics(db)


@router.get("/v1/teaching/policy")
async def get_teaching_policy(
    student_id: UUID,
    ku_id: str,
    context: str = Query("system_taught"),
    _auth: User = Depends(require_student_access),
    db: AsyncSession = Depends(get_db),
):
    """L2 教学引擎：返回该 (学生, KU, 情境) 下的答案分级政策 + 当前学习阶段。
    情境 context: system_taught(系统同构新知) / own_homework(自带原题) / writing(写作) / stuck(卡壳)。
    前端据此决定"给完整样例"还是"苏格拉底提问"。红线：own_homework/writing 恒不给。
    教学引擎 feature-flag(TEACHING_ENGINE_ENABLED) 关闭时保守回退 never。"""

    from oprim.answer_policy import answer_policy

    from services.learner_model import get_mastery, get_stage

    m = await get_mastery(db, student_id, ku_id)
    stage = get_stage(m["p"])
    from services.experiment_service import student_arm, teaching_engine_on_for

    enabled = teaching_engine_on_for(student_id)  # 全局 flag 或 RCT 臂=worked_example
    pol = answer_policy(context, stage, enabled=enabled)
    return {
        "stage": stage,
        "engine_enabled": enabled,
        "experiment_arm": student_arm(student_id),
        **pol,
    }


class PlacementResponse(BaseModel):
    difficulty: float = Field(ge=0.0, le=1.0)
    is_correct: bool


class PlacementReq(BaseModel):
    responses: list[PlacementResponse]


@router.post("/v1/placement/estimate")
async def post_placement_estimate(
    body: PlacementReq,
    _auth: User = Depends(get_current_user),
):
    """L3 自适应定位：从一批 (难度, 对错) 响应估学生能力 θ(Rasch)+ SE + ZPD 难度带 +
    建议下一题难度。冷启动/入学定位用；θ 也可喂 learner_model.get_zpd_band。纯计算不落库。"""
    from oprim.ability import estimate_ability, next_item_difficulty

    from services.learner_model import get_zpd_band

    est = estimate_ability([(r.difficulty, r.is_correct) for r in body.responses])
    theta = est["theta"]
    return {
        **est,
        "zpd_band": get_zpd_band(None, theta=theta),
        "next_difficulty": next_item_difficulty(theta),
    }


class CatResponse(BaseModel):
    difficulty: float = Field(ge=0.0, le=1.0)
    is_correct: bool


class CatNextReq(BaseModel):
    subject: str = "math"
    responses: list[CatResponse] = Field(default_factory=list)
    served_ku_ids: list[str] = Field(default_factory=list)


@router.post("/v1/placement/next")
async def post_placement_next(
    body: CatNextReq,
    _auth: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """L3 自适应定位会话(CAT,无状态)：交累积 (难度,对错) → 估 θ,SE<阈值或达上限即停,
    否则返回难度就近 θ 的下一题 KU。客户端累积 responses/served_ku_ids 逐轮调用。"""

    return await cat_next(
        db,
        subject=body.subject,
        responses=[r.model_dump() for r in body.responses],
        served_ku_ids=body.served_ku_ids,
    )


@router.get("/v1/misconception/{ku_id}")
async def get_misconception(
    ku_id: str,
    distractor: str | None = Query(None),
    _auth: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """L3 误解诊断（骨架）：答错时挂误解 ID + 重建方向，用于概念重建微课而非同类题再刷。
    优先精确干扰项映射(教研逐题填)，否则按 KU 名关键词退回候选(heuristic)。"""
    from oprim.misconception import diagnose_misconception

    row = (
        await db.execute(
            select(KnowledgeUnit.name, Textbook.subject)
            .join(Textbook, KnowledgeUnit.textbook_id == Textbook.id)
            .where(KnowledgeUnit.id == ku_id)
        )
    ).first()
    if row is None:
        return {"misconception": None, "note": "KU 不存在"}
    name, subject = row
    m = diagnose_misconception(
        subject or "", name or "", ku_id=ku_id, distractor=distractor
    )
    return {"ku_id": ku_id, "misconception": m}


@router.get("/v1/moat/experiment/{name}")
async def get_experiment_metrics(
    name: str,
    _auth: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """RCT 按臂主终点(延迟保持率/挫败流失率)。首个实验 teaching_engine_v1：样例渐退 vs 纯苏格拉底。
    登录可读,聚合无 PII。实验 env 关时所有人 control(现网零变化)。"""
    from services.experiment_service import experiment_metrics

    return await experiment_metrics(db, name)


