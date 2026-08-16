"""认知状态 / 掌握度 / 知识单元（自 main 拆出）。"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from obase.db import get_db
from omodul.cognitive import InteractionInput
from oprim.chinese_track import chinese_track as _chinese_track
from oprim.prereq_graph import topo_sort_by_prereq
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from data.guangdong_math_kc import KC_LIST, get_kc
from services.auth_deps import (
    _ensure_student_access,
    _ensure_student_self,
    get_current_user,
    require_student_access,
)
from services.cognitive_service import mastery_overview, process_interaction
from services.feature_flags import PEDAGOGY_FRINGE, pedagogy_enabled
from services.models import (
    KCMastery,
    KnowledgeCluster,
    KnowledgeUnit,
    MasterySnapshot,
    Textbook,
    TextbookFile,
    User,
)
from services.route_helpers import grade_sort_key as _grade_sort_key

router = APIRouter(tags=["cognitive"])

# ===== §8 认知状态 API =====


@router.post("/v1/interaction")
async def post_interaction(
    interaction: InteractionInput,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """POST /v1/interaction — 处理一次答题交互并更新认知状态。仅学生本人可写。"""
    _ensure_student_self(current_user, interaction.student_id)
    try:
        result = await process_interaction(
            db,
            student_id=interaction.student_id,
            kc_id=interaction.ku_id,
            is_correct=interaction.is_correct,
            question_type=interaction.question_type,
            question_id=interaction.question_id,
            source=interaction.source,
            used_answer=interaction.used_answer,
            struggled=interaction.struggled,
            effortless=interaction.effortless,
            is_interleaved=interaction.is_interleaved,
            time_spent_seconds=interaction.time_spent_seconds,
            difficulty=interaction.difficulty,
            predicted_confidence=interaction.predicted_confidence,
            now=interaction.now,
        )
        await db.commit()
        return result
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/v1/mastery/curve/{student_id}/{ku_id}")
async def get_mastery_curve(
    student_id: UUID,
    ku_id: str,
    _auth: User = Depends(require_student_access),
    db: AsyncSession = Depends(get_db),
):
    """GET /v1/mastery/curve/{student_id}/{ku_id} — mastery_snapshots 月度时间序列。"""
    rows = (
        (
            await db.execute(
                select(MasterySnapshot)
                .where(MasterySnapshot.student_id == student_id)
                .where(MasterySnapshot.knowledge_point == ku_id)
                .order_by(MasterySnapshot.snapshot_month)
            )
        )
        .scalars()
        .all()
    )
    kc = await db.get(KnowledgeUnit, ku_id)
    _kcd = get_kc(ku_id)
    return {
        "ku_id": ku_id,
        "ku_name": (kc.name if kc else ((_kcd.get("name") if _kcd else None) or ku_id)),
        "points": [
            {
                "month": r.snapshot_month.isoformat(),
                "mastery": round(r.long_term_mastery, 4) if r.long_term_mastery else 0,
                "dominant_error_type": r.dominant_error_type,
            }
            for r in rows
        ],
    }


@router.get("/v1/mastery/gate-check/{student_id}/{ku_id}")
async def get_mastery_gate_check(
    student_id: UUID,
    ku_id: str,
    _auth: User = Depends(require_student_access),
    db: AsyncSession = Depends(get_db),
):
    """GET /v1/mastery/gate-check/{student_id}/{ku_id} — U.17 掌握裁决（发起）。

    现场生成一道内核核验题（不落库、不进练习池），从不返回答案。
    """
    from services.mastery_gate_service import start_gate_check

    return await start_gate_check(db, student_id, ku_id)


class MasteryGateSubmitReq(BaseModel):
    student_answer: str


@router.post("/v1/mastery/gate-check/{student_id}/{ku_id}")
async def post_mastery_gate_check(
    student_id: UUID,
    ku_id: str,
    req: MasteryGateSubmitReq,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """POST /v1/mastery/gate-check/{student_id}/{ku_id} — U.17 掌握裁决（提交）。

    仅学生本人：这会写 KCMastery.mastery_confirmed=True，属于替孩子写掌握状态记录，
    家长不可代答（同其它认知写入红线）。发起端（GET）是只读生成题目，家长可看。
    答对 → mastery_confirmed=True（独立于 BKT p_mastery，不改动算法状态）。
    """
    _ensure_student_self(current_user, student_id)
    from services.mastery_gate_service import submit_gate_check

    return await submit_gate_check(db, student_id, ku_id, req.student_answer)


@router.get("/v1/mastery/{student_id}")
async def get_mastery(
    student_id: UUID,
    now: datetime | None = None,
    _auth: User = Depends(require_student_access),
    db: AsyncSession = Depends(get_db),
):
    """GET /v1/mastery/{student_id} — 掌握度总览（按薄弱排序，含百分位）。"""
    try:
        items = await mastery_overview(db, student_id, now=now)
        # 补 KU 友好名称（命名已统一），避免前端标题空白/显示原始 id
        if isinstance(items, list) and items:
            ids = list({it.get("ku_id") for it in items if it.get("ku_id")})
            if ids:
                krows = (
                    await db.execute(
                        select(KnowledgeUnit.id, KnowledgeUnit.name).where(
                            KnowledgeUnit.id.in_(ids)
                        )
                    )
                ).all()
                nm = {kid: name for kid, name in krows}
                for it in items:
                    kid = it.get("ku_id")
                    name = nm.get(kid)
                    if not name:  # 回退广东 KC 字典(GDMATH-* 等老命名)
                        kc = get_kc(kid)
                        name = (kc.get("name") if kc else None) or kid
                    it["ku_name"] = name
        return items
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# review-queue → services/routers/review.py

@router.get("/v1/ku")
async def list_kc():
    """
    GET /v1/ku
    获取全部知识点字典。KC_LIST 内部字典的 key 仍叫 kc_id（data/guangdong_math_kc.py
    内部实现，不是 API 契约，不改），这里响应体边界处把每条的 kc_id 重命名成 ku_id 对外。
    """
    out = []
    for kc in KC_LIST:
        kc_out = dict(kc)
        kc_out["ku_id"] = kc_out.pop("kc_id")
        out.append(kc_out)
    return out


@router.get("/v1/ku/{ku_id}")
async def get_kc_detail(ku_id: str):
    """
    GET /v1/ku/{ku_id}
    获取特定知识点详情。get_kc() 内部字典的 key 仍叫 kc_id（data/guangdong_math_kc.py
    内部实现，不是 API 契约，不改），这里响应体边界处把 kc_id 重命名成 ku_id 对外。
    """
    kc = get_kc(ku_id)
    if not kc:
        raise HTTPException(status_code=404, detail="Knowledge Component not found")
    kc_out = dict(kc)
    kc_out["ku_id"] = kc_out.pop("kc_id")
    return kc_out


# ===== §2b 知识单元接口（DB 版，替代旧 KC 字典）=====


async def _textbook_file_map(
    db: AsyncSession, textbook_ids: list[str]
) -> dict[str, str]:
    """返回 {textbook_id: file_id}，取每个教材的第一个平台预置 PDF。"""
    if not textbook_ids:
        return {}
    rows = (
        await db.execute(
            select(TextbookFile.textbook_id, TextbookFile.id)
            .where(
                TextbookFile.textbook_id.in_(textbook_ids),
                TextbookFile.owner_student_id.is_(None),
                TextbookFile.file_type == "pdf",
            )
            .order_by(TextbookFile.uploaded_at)
        )
    ).all()
    # 每个 textbook_id 只取第一条
    result: dict[str, str] = {}
    for tid, fid in rows:
        if tid not in result:
            result[tid] = fid
    return result


async def _mastery_map(
    db: AsyncSession, student_id: UUID, ku_ids: list[str]
) -> dict[str, float]:
    """返回 {ku_id: p_mastery}，只查询该学生。"""
    if not ku_ids or not student_id:
        return {}
    rows = (
        await db.execute(
            select(KCMastery.knowledge_point, KCMastery.p_mastery).where(
                KCMastery.student_id == student_id,
                KCMastery.knowledge_point.in_(ku_ids),
            )
        )
    ).all()
    return {kp: (pm or 0.0) for kp, pm in rows}


def _mastery_color(p: float | None) -> str:
    # L1 单源：委托 learner_model.mastery_color（阈值统一在那里）
    from services.learner_model import mastery_color

    return mastery_color(p)


def _fringe(
    p_mastery: float | None,
    prerequisites: list[str] | None,
    mastery_map: dict[str, float | None],
) -> str:
    # L1 单源：委托 learner_model.fringe（阈值统一在那里，不直接调 oprim.prereq_graph）
    from services.learner_model import fringe

    return fringe(p_mastery, prerequisites, mastery_map)


_FREQ_RANK = {"high": 2, "mid": 1, "low": 0}
_MASTERY_RANK = {"red": 0, "yellow": 1, "unknown": 2, "green": 3}


# 拓扑排序已上移至 oprim.prereq_graph.topo_sort_by_prereq（确定性算法归 oprim）


@router.get("/v1/knowledge-points")
async def list_knowledge_points(
    subject: str | None = Query(None),
    textbook_id: str | None = Query(None),
    cluster_id: str | None = Query(None),
    student_id: UUID | None = Query(None),
    sort: str = Query("chapter"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    GET /v1/knowledge-points
    查询知识单元，支持按 subject / textbook_id / cluster_id 筛选。
    可选 student_id → 附带该生掌握度（p_mastery / mastery_color）。
    sort: chapter(默认)|topic|mastery|difficulty|exam_freq|prereq
    返回带 cluster 信息、textbook_file_id 和 AII 字段的 KU 列表。
    """
    await _ensure_student_access(db, current_user, student_id)
    stmt = (
        select(KnowledgeUnit, KnowledgeCluster, Textbook)
        .join(KnowledgeCluster, KnowledgeUnit.cluster_id == KnowledgeCluster.id)
        .join(Textbook, KnowledgeUnit.textbook_id == Textbook.id)
    )
    if subject:
        stmt = stmt.where(Textbook.subject == subject)
    if textbook_id:
        stmt = stmt.where(KnowledgeUnit.textbook_id == textbook_id)
    if cluster_id:
        stmt = stmt.where(KnowledgeUnit.cluster_id == cluster_id)
    stmt = stmt.order_by(KnowledgeCluster.display_order, KnowledgeUnit.id)

    rows = (await db.execute(stmt)).all()

    # 批量查 textbook_file_id 和学生掌握度（各1次查询）
    all_tb_ids = list({tb.id for _, _, tb in rows})
    all_ku_ids = [ku.id for ku, _, _ in rows]
    file_map = await _textbook_file_map(db, all_tb_ids)
    mastery_map = await _mastery_map(db, student_id, all_ku_ids) if student_id else {}

    fringe_enabled = pedagogy_enabled(
        PEDAGOGY_FRINGE
    )  # U.24（PEDAGOGY_FRINGE_ENABLED=0 急停）

    items = [
        {
            "id": ku.id,
            "name": ku.name,
            "description": ku.description,
            "textbook_id": ku.textbook_id,
            "textbook_file_id": file_map.get(ku.textbook_id),
            "cluster_id": ku.cluster_id,
            "cluster_name": kc.name,
            "cluster_order": kc.display_order,
            "subject": tb.subject,
            "grade": tb.grade,
            "edition": tb.edition,
            "book_name": tb.book_name,
            "prerequisites": ku.prerequisites,
            "soft_prerequisites": ku.soft_prerequisites,
            "related_kus": ku.related_kus,
            "difficulty": round(ku.difficulty, 4),
            "exam_frequency": ku.exam_frequency,
            "question_types": ku.question_types,
            "ku_type": ku.ku_type,
            "curriculum_standard": ku.curriculum_standard,
            "mastery_levels": ku.mastery_levels,
            "verified": ku.verified,
            "p_mastery": mastery_map.get(ku.id),
            "mastery_color": _mastery_color(mastery_map.get(ku.id)),
            # KST fringe（掌握门控，U.24 教育理念01）：mastered/learning/learnable/locked；
            # 仅在有 student 且开关开启时有意义
            "fringe": (
                _fringe(mastery_map.get(ku.id), ku.prerequisites, mastery_map)
                if student_id and fringe_enabled
                else None
            ),
            # L4 语文双轨：记诵轨(FSRS)/素养轨(策略)，供前端路由；非语文为 None
            "track": _chinese_track(ku.ku_type) if tb.subject == "chinese" else None,
        }
        for ku, kc, tb in rows
    ]

    if sort == "textbook":
        items.sort(
            key=lambda x: (
                _grade_sort_key(x["grade"]),
                x["textbook_id"].lower(),
                x["id"],
            )
        )
    elif sort == "topic":
        items.sort(key=lambda x: (x["cluster_name"], x["id"]))
    elif sort == "mastery":
        items.sort(
            key=lambda x: (
                _MASTERY_RANK.get(x["mastery_color"], 2),
                -(x["p_mastery"] or 0),
            )
        )
    elif sort == "difficulty":
        items.sort(key=lambda x: x["difficulty"])
    elif sort == "exam_freq":
        items.sort(key=lambda x: -_FREQ_RANK.get(x["exam_frequency"], 1))
    elif sort == "prereq":
        items = topo_sort_by_prereq(items)

    # verified 优先（稳定排序，保留各 sort 模式内的相对顺序）；
    # prereq 拓扑序是硬约束，不参与重排
    if sort != "prereq":
        items.sort(key=lambda x: not x["verified"])

    return items


@router.get("/v1/knowledge-points/{ku_id}")
async def get_knowledge_point(
    ku_id: str,
    student_id: UUID | None = Query(None),
    low_bandwidth: bool = Query(
        False, description="U.23：跳过 rich_content（讲透内容，通常最大的字段）"
    ),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """GET /v1/knowledge-points/{ku_id} — 单个 KU 详情（含掌握度和前置KU掌握度）。"""
    await _ensure_student_access(db, current_user, student_id)
    row = (
        await db.execute(
            select(KnowledgeUnit, KnowledgeCluster, Textbook)
            .join(KnowledgeCluster, KnowledgeUnit.cluster_id == KnowledgeCluster.id)
            .join(Textbook, KnowledgeUnit.textbook_id == Textbook.id)
            .where(KnowledgeUnit.id == ku_id)
        )
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="KnowledgeUnit not found")
    ku, kc, tb = row

    file_map = await _textbook_file_map(db, [ku.textbook_id])
    # 掌握度：当前 KU + 所有前置 KU
    prereq_ids = list(ku.prerequisites) if ku.prerequisites else []
    all_ids = [ku_id] + prereq_ids
    mastery_map = await _mastery_map(db, student_id, all_ids) if student_id else {}

    prereq_mastery = [
        {
            "ku_id": pid,
            "p_mastery": mastery_map.get(pid),
            "mastery_color": _mastery_color(mastery_map.get(pid)),
        }
        for pid in prereq_ids
    ]

    return {
        "id": ku.id,
        "name": ku.name,
        "description": ku.description,
        "textbook_id": ku.textbook_id,
        "textbook_file_id": file_map.get(ku.textbook_id),
        "cluster_id": ku.cluster_id,
        "cluster_name": kc.name,
        "subject": tb.subject,
        "grade": tb.grade,
        "prerequisites": ku.prerequisites,
        "soft_prerequisites": ku.soft_prerequisites,
        "related_kus": ku.related_kus,
        "difficulty": round(ku.difficulty, 4),
        "exam_frequency": ku.exam_frequency,
        "question_types": ku.question_types,
        "ku_type": ku.ku_type,
        "curriculum_standard": ku.curriculum_standard,
        "exam_region_tags": ku.exam_region_tags,  # U.21 骨架
        "textbook_edition_variant_of": ku.textbook_edition_variant_of,  # U.21 骨架
        "mastery_levels": ku.mastery_levels,
        "p_mastery": mastery_map.get(ku_id),
        "mastery_color": _mastery_color(mastery_map.get(ku_id)),
        "prereq_mastery": prereq_mastery,
        "rich_content": None if low_bandwidth else ku.rich_content,
    }


@router.get("/v1/curriculum-standards/{code}/kus")
async def get_kus_by_curriculum_standard(
    code: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """GET /v1/curriculum-standards/{code}/kus — U.21 课标反查：哪些 KU 挂了这个课标编码。

    双向映射的"反向"一侧（KU→课标已在 /v1/knowledge-points/{ku_id} 的 curriculum_standard
    字段里）；code 的合法性/节点信息见 data/curriculum_std.py（义教2022/高中2017课标骨架，
    数学 only，其余学科暂无课标编码体系）。
    """
    from data.curriculum_std import get_node

    node = get_node(code)
    rows = (
        (
            await db.execute(
                select(KnowledgeUnit).where(KnowledgeUnit.curriculum_standard == code)
            )
        )
        .scalars()
        .all()
    )
    return {
        "code": code,
        "node": node,  # None = 不是已知合法编码（不代表查询失败，只是未登记）
        "kus": [{"id": ku.id, "name": ku.name} for ku in rows],
        "count": len(rows),
    }


