"""U.21 课标编码质检门（curriculum_standard 结构一致性）。

只做机械结构校验，不判断语义是否精准贴题（语义靠人工抽查/更强 LLM）：
  1. 编码本身是否在 data/curriculum_std.py 的 STD_NODES 里合法存在。
  2. 编码的 seg（JY/GZ）是否与该 KU 所在教材的学段吻合
     （通过 textbook_id/grade 猜测学段，逻辑与 tag_curriculum_standard_pilot.py 的
     _guess_seg 保持一致，避免子串误判如 "G1" 命中 "G10"）。
  3. JY 段编码进一步核对 stage（小学/初中）是否与年级吻合——
     踩过的坑：G8 教材条目被打上 stage=小学 的编码（如 GM-RM 用于初中轴对称）。

用法：
    python scripts/qc_curriculum_standard.py                 # 全量
    python scripts/qc_curriculum_standard.py --subject math  # 限学科
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

from data.curriculum_std import get_node  # noqa: E402
from obase.config import settings  # noqa: E402
from services.models import KnowledgeUnit, Textbook  # noqa: E402

_JY_GRADE_NUMS = (1, 2, 3, 4, 5, 6, 7, 8, 9)
_GZ_GRADE_NUMS = (10, 11, 12)
_JY_TEXT_MARKERS = (
    "小学",
    "初中",
    "一年级",
    "二年级",
    "三年级",
    "四年级",
    "五年级",
    "六年级",
    "七年级",
    "八年级",
    "九年级",
)
_GZ_TEXT_MARKERS = ("高一", "高二", "高三", "高中")
_PRIMARY_GRADE_NUMS = (1, 2, 3, 4, 5, 6)
_JUNIOR_GRADE_NUMS = (7, 8, 9)


def _has_grade_marker(hay: str, grade_nums: tuple[int, ...]) -> bool:
    return any(re.search(rf"\bG{n}\b", hay, re.IGNORECASE) for n in grade_nums)


def _guess_seg(textbook_id: str, grade: str) -> str | None:
    hay = f"{textbook_id} {grade}"
    if _has_grade_marker(hay, _JY_GRADE_NUMS) or any(
        m in hay for m in _JY_TEXT_MARKERS
    ):
        return "JY"
    if _has_grade_marker(hay, _GZ_GRADE_NUMS) or any(
        m in hay for m in _GZ_TEXT_MARKERS
    ):
        return "GZ"
    return None


def _guess_jy_stage(textbook_id: str, grade: str) -> str | None:
    """JY 段进一步猜测：小学（G1-G6）还是初中（G7-G9）。"""
    hay = f"{textbook_id} {grade}"
    if (
        _has_grade_marker(hay, _PRIMARY_GRADE_NUMS)
        or "小学" in hay
        or any(f"{n}年级" in hay for n in ("一", "二", "三", "四", "五", "六"))
    ):
        return "小学"
    if (
        _has_grade_marker(hay, _JUNIOR_GRADE_NUMS)
        or "初中" in hay
        or any(f"{n}年级" in hay for n in ("七", "八", "九"))
    ):
        return "初中"
    return None


def check_one(ku_id: str, code: str, textbook_id: str, grade: str) -> list[str]:
    problems: list[str] = []
    node = get_node(code)
    if node is None:
        return [f"编码 {code} 不存在于 STD_NODES"]

    expected_seg = _guess_seg(textbook_id, grade)
    if expected_seg is not None and node.get("seg") != expected_seg:
        problems.append(
            f"学段不符：编码 seg={node.get('seg')}，教材推断学段={expected_seg}"
        )
        return problems  # seg 都错了，stage 没必要再查

    if node.get("seg") == "JY":
        expected_stage = _guess_jy_stage(textbook_id, grade)
        node_stage = node.get("stage")
        if (
            expected_stage is not None
            and node_stage in ("小学", "初中")
            and node_stage != expected_stage
        ):
            problems.append(
                f"义教子学段不符：编码 stage={node_stage}，教材推断子学段={expected_stage}"
            )
    return problems


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--subject", default="math")
    args = ap.parse_args()

    engine = create_async_engine(settings.DATABASE_URL)
    async with engine.connect() as conn:
        stmt = (
            select(
                KnowledgeUnit.id,
                KnowledgeUnit.curriculum_standard,
                KnowledgeUnit.textbook_id,
                Textbook.grade,
            )
            .join(Textbook, KnowledgeUnit.textbook_id == Textbook.id)
            .where(Textbook.subject == args.subject)
            .where(KnowledgeUnit.curriculum_standard.is_not(None))
        )
        rows = (await conn.execute(stmt)).all()
    await engine.dispose()

    flagged: list[tuple[str, list[str]]] = []
    for kid, code, textbook_id, grade in rows:
        probs = check_one(kid, code, textbook_id, grade or "")
        if probs:
            flagged.append((kid, probs))

    print(
        f"质检 {len(rows)} 个已打标 KU：{len(rows) - len(flagged)} 通过 / {len(flagged)} 有问题。"
    )
    for kid, probs in flagged:
        print(f"  ✗ {kid}: {'; '.join(probs)}")

    sys.exit(1 if flagged else 0)


if __name__ == "__main__":
    asyncio.run(main())
