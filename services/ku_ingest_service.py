"""KU 录入校验门（item 2：提取可信度，防 AI 幻觉污染权威知识库）。

红线：LLM 抽取的课程 KU **不得绕过校验直写** knowledge_units。
本服务在录入边界做确定性校验 + 溯源/源-AI 分离落库：
- 校验门 validate_curriculum_ku：必填字段、描述质量、前置边引用合法、难度区间。
- store_curriculum_ku：过门者入库并写 provenance / source_excerpt / ai_generated /
  verified；未过门进 rejected，不进权威表。

任何抽取脚本/上传流水线都应调 store_curriculum_ku，而非裸 INSERT。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.models import KnowledgeUnit

_MIN_DESC_CHARS = 8


def validate_curriculum_ku(ku: dict, known_ku_ids: Optional[set[str]] = None) -> tuple[bool, list[str]]:
    """确定性校验一条课程 KU 候选。返回 (是否通过, 错误列表)。

    宁可拒之门外，不让幻觉/残缺 KU 成为权威真值。
    """
    errors: list[str] = []
    kid = (ku.get("id") or "").strip()
    name = (ku.get("name") or "").strip()
    desc = (ku.get("description") or "").strip()
    if not kid:
        errors.append("missing id")
    if not name:
        errors.append("missing name")
    if len(desc) < _MIN_DESC_CHARS:
        errors.append(f"description too short (<{_MIN_DESC_CHARS} chars)")
    # 难度区间
    diff = ku.get("difficulty", 0.5)
    try:
        if not (0.0 <= float(diff) <= 1.0):
            errors.append("difficulty out of [0,1]")
    except (TypeError, ValueError):
        errors.append("difficulty not numeric")
    # 前置边必须引用已知 KU（避免悬空/幻觉前置）；known 未提供则跳过该校验
    prereqs = ku.get("prerequisites") or []
    if known_ku_ids is not None:
        for p in prereqs:
            if p not in known_ku_ids and p != kid:
                errors.append(f"unknown prerequisite: {p}")
    # 自指前置
    if kid and kid in prereqs:
        errors.append("self-referential prerequisite")
    return (len(errors) == 0, errors)


async def store_curriculum_ku(
    db: AsyncSession,
    ku: dict,
    *,
    source_excerpt: str = "",
    provenance: Optional[dict] = None,
    known_ku_ids: Optional[set[str]] = None,
    extract_model: str = "unknown",
) -> dict:
    """过校验门后落库一条 KU（含溯源 + 源/AI 分离）。未过门返回 rejected。"""
    valid, errors = validate_curriculum_ku(ku, known_ku_ids)
    if not valid:
        return {"status": "rejected", "ku_id": ku.get("id"), "errors": errors}

    prov = dict(provenance or {})
    prov.setdefault("extract_model", extract_model)
    prov.setdefault("extracted_at", datetime.now(timezone.utc).isoformat())

    existing = (await db.execute(
        select(KnowledgeUnit).where(KnowledgeUnit.id == ku["id"])
    )).scalar_one_or_none()

    fields = dict(
        name=ku["name"],
        description=ku.get("description"),
        prerequisites=ku.get("prerequisites") or [],
        difficulty=float(ku.get("difficulty", 0.5)),
        provenance=prov,
        source_excerpt=source_excerpt,
        ai_generated=True,           # LLM 抽取
        verified=True,               # 过确定性校验门
    )
    if existing:
        for k, v in fields.items():
            setattr(existing, k, v)
    else:
        db.add(KnowledgeUnit(
            id=ku["id"],
            textbook_id=ku.get("textbook_id", "unknown"),
            cluster_id=ku.get("cluster_id", "unknown"),
            **fields,
        ))
    await db.flush()
    return {"status": "stored", "ku_id": ku["id"], "verified": True}


async def store_curriculum_kus(
    db: AsyncSession,
    kus: Iterable[dict],
    *,
    source_excerpt_map: Optional[dict[str, str]] = None,
    known_ku_ids: Optional[set[str]] = None,
    extract_model: str = "unknown",
) -> dict:
    """批量录入。返回 {stored, rejected, rejected_details}。"""
    src = source_excerpt_map or {}
    stored, rejected, details = 0, 0, []
    for ku in kus:
        res = await store_curriculum_ku(
            db, ku,
            source_excerpt=src.get(ku.get("id", ""), ""),
            provenance=ku.get("provenance"),
            known_ku_ids=known_ku_ids,
            extract_model=extract_model,
        )
        if res["status"] == "stored":
            stored += 1
        else:
            rejected += 1
            details.append(res)
    return {"stored": stored, "rejected": rejected, "rejected_details": details}
