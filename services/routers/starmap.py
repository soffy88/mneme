"""Starmap per-student mastery API (Word Atlas deployment step 2).

只读接口：按**当前登录学生本人**返回其掌握数据，绝不接受他人 student_id，
因此不存在 IDOR 面：查询条件恒为 ``KCMastery.student_id == current_user.id``。

状态口径（沿用集成报告，不得自创阈值）：
- 已掌握（``掌握``）：BKT ``p_mastery >= learner_model.MASTERED (0.7)``
  或 FSRS ``fsrs_card_json.stability >= wordatlas_fsrs.MASTERED_STABILITY_DAYS (21 天)``。
- 学习中（``学习中``）：有 ``kc_mastery`` 行，但两项阈值均未达标。
- 未学（``未学``）：无 ``kc_mastery`` 行。
- BKT 是掌握裁决源，FSRS 稳定度是复测排期口径：两值分开返回；
  ``mastery_basis`` 标明点亮来自哪一侧（``bkt`` / ``fsrs`` / ``both``），
  FSRS 单侧点亮时解读仍以 BKT 为准（见 ``mastery_basis == "fsrs"`` 的卡片注记）。

数据来源唯一：``kc_mastery``（``knowledge_point`` = KU id，
``fsrs_card_json.stability`` 单位为天）。不读、不聚合任何其他学生的行。
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Body, Depends, Query
from obase.db import get_db
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.auth_deps import get_current_user
from services.learner_model import MASTERED
from services.models import KCMastery, User
from services.wordatlas_fsrs import MASTERED_STABILITY_DAYS

router = APIRouter(tags=["starmap"])

MAX_KU_IDS = 5000

STATUS_MASTERED = "掌握"
STATUS_LEARNING = "学习中"
STATUS_UNLEARNED = "未学"


def starmap_status(
    p_mastery: Optional[float], fsrs_stability_days: Optional[float]
) -> tuple[str, Optional[str]]:
    """纯函数：由两值算状态与点亮来源。

    返回 ``(status, mastery_basis)``；未掌握时 basis 为 None。
    ``has_row`` 由调用方保证：无行时调用方直接返回未学，不走本函数。
    """
    bkt_ok = p_mastery is not None and p_mastery >= MASTERED
    fsrs_ok = (
        fsrs_stability_days is not None
        and fsrs_stability_days >= MASTERED_STABILITY_DAYS
    )
    if bkt_ok and fsrs_ok:
        return STATUS_MASTERED, "both"
    if bkt_ok:
        return STATUS_MASTERED, "bkt"
    if fsrs_ok:
        return STATUS_MASTERED, "fsrs"
    return STATUS_LEARNING, None


def _item_for(ku_id: str, row: Optional[KCMastery]) -> dict:
    if row is None:
        return {
            "ku_id": ku_id,
            "bkt_p_mastery": None,
            "fsrs_stability_days": None,
            "status": STATUS_UNLEARNED,
            "mastery_basis": None,
        }
    card = row.fsrs_card_json or {}
    stability = card.get("stability")
    stability_days = float(stability) if stability is not None else None
    p = float(row.p_mastery) if row.p_mastery is not None else None
    status, basis = starmap_status(p, stability_days)
    return {
        "ku_id": ku_id,
        "bkt_p_mastery": p,
        "fsrs_stability_days": stability_days,
        "status": status,
        "mastery_basis": basis,
    }


async def _mastery_for(
    db: AsyncSession, student_id, ku_ids: Optional[list[str]]
) -> dict:
    """核心查询：只查当前学生本人的行；ku_ids 为空时返回该生全部行。"""
    if ku_ids is not None:
        wanted: list[str] = []
        seen: set[str] = set()
        for ku_id in ku_ids:
            if ku_id and ku_id not in seen:
                seen.add(ku_id)
                wanted.append(ku_id)
        stmt = (
            select(KCMastery)
            .where(
                KCMastery.student_id == student_id,
                KCMastery.knowledge_point.in_(wanted),
            )
            .order_by(KCMastery.knowledge_point)
        )
        rows = (await db.execute(stmt)).scalars().all()
        by_kp = {r.knowledge_point: r for r in rows}
        items = [_item_for(ku_id, by_kp.get(ku_id)) for ku_id in wanted]
    else:
        stmt = (
            select(KCMastery)
            .where(KCMastery.student_id == student_id)
            .order_by(KCMastery.knowledge_point)
        )
        rows = (await db.execute(stmt)).scalars().all()
        items = [_item_for(r.knowledge_point, r) for r in rows]
    counts = {STATUS_MASTERED: 0, STATUS_LEARNING: 0, STATUS_UNLEARNED: 0}
    for item in items:
        counts[item["status"]] += 1
    return {
        "student_id": str(student_id),
        "count": len(items),
        "counts": counts,
        "items": items,
    }


class StarmapMasteryReq(BaseModel):
    ku_ids: list[str] = Field(default_factory=list)


@router.get("/v1/starmap/mastery")
async def get_starmap_mastery(
    ku_id: list[str] = Query(default=[]),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """按登录学生返回掌握数据。

    ``ku_id`` 可重复传（请求范围）；不传则返回该生全部 ``kc_mastery`` 行。
    全量星图（1,187 个 KU）请走 POST（body，不受 URL 长度限制）。
    """
    ku_ids = ku_id or None
    if ku_ids is not None and len(ku_ids) > MAX_KU_IDS:
        ku_ids = ku_ids[:MAX_KU_IDS]
    return await _mastery_for(db, current_user.id, ku_ids)


@router.post("/v1/starmap/mastery")
async def post_starmap_mastery(
    payload: StarmapMasteryReq = Body(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """POST 版：body 传 ``ku_ids``，用于全量星图 1,187 个 KU 一次取数。"""
    ku_ids = payload.ku_ids or None
    if ku_ids is not None and len(ku_ids) > MAX_KU_IDS:
        ku_ids = ku_ids[:MAX_KU_IDS]
    return await _mastery_for(db, current_user.id, ku_ids)
