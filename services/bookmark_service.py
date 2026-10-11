"""bookmark_service —— 学生的题目收藏（☆，/v2/practice/bookmarks）。

两类可收藏的题：
- posed：RequestQuestion 出给本人的待答题（gate.pending_question 中的 q-…）；
- wrong：本人错题（wrong_questions.id）。

题干快照、KC 一律由**服务端**按 (student_id, question_id) 取，不信任客户端传入的文本；
归属不符 / 不存在 → None（路由层 404）。红线：参考答案（expected / correct_answer）
永不读入返回体、永不落入本表；收藏不写证据、不改掌握度/FSRS、不 import 判分/门控写入模块。
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

SOURCES = ("posed", "wrong")

_COLS = "id, source, question_ref, wrong_question_id, kc_id, prompt, qtype, created_at"


def _row(r: Any) -> dict:
    m = dict(r._mapping)
    return {
        "id": str(m["id"]),
        "source": m["source"],
        "question_id": m["question_ref"],
        "wrong_question_id": str(m["wrong_question_id"]) if m["wrong_question_id"] else None,
        "kc_id": m["kc_id"],
        "prompt": m["prompt"],
        "qtype": m["qtype"],
        "created_at": m["created_at"].isoformat() if m["created_at"] else None,
    }


async def _resolve(
    db: AsyncSession, student_id: uuid.UUID, source: str, question_id: str
) -> Optional[dict]:
    """按归属取题干快照（不取答案列）。"""
    if source == "posed":
        r = (
            await db.execute(
                text(
                    "SELECT kc_id, prompt, qtype FROM gate.pending_question "
                    "WHERE student_id = CAST(:sid AS uuid) AND question_id = :qid"
                ),
                {"sid": str(student_id), "qid": question_id},
            )
        ).first()
        if r is None:
            return None
        return {"kc_id": r[0], "prompt": r[1] or "", "qtype": r[2], "wrong_question_id": None}
    try:
        wq_id = uuid.UUID(question_id)
    except ValueError:
        return None
    r = (
        await db.execute(
            text(
                "SELECT id, question_text, knowledge_points FROM wrong_questions "
                "WHERE id = :id AND student_id = :sid"
            ),
            {"id": wq_id, "sid": student_id},
        )
    ).first()
    if r is None:
        return None
    kps = r[2] or {}
    kc = next(iter(kps), None) if isinstance(kps, dict) else None
    return {"kc_id": kc, "prompt": r[1] or "", "qtype": None, "wrong_question_id": r[0]}


async def add_bookmark(
    db: AsyncSession, student_id: uuid.UUID, source: str, question_id: str
) -> Optional[dict]:
    """幂等收藏：同一题重复收藏返回既有记录。题不存在/非本人 → None。"""
    if source not in SOURCES:
        raise ValueError("source must be posed or wrong")
    q = await _resolve(db, student_id, source, question_id)
    if q is None:
        return None
    await db.execute(
        text(
            "INSERT INTO question_bookmarks "
            "(student_id, source, question_ref, wrong_question_id, kc_id, prompt, qtype) "
            "VALUES (:sid, :src, :ref, :wq, :kc, :prompt, :qtype) "
            "ON CONFLICT (student_id, source, question_ref) DO NOTHING"
        ),
        {
            "sid": student_id,
            "src": source,
            "ref": question_id,
            "wq": q["wrong_question_id"],
            "kc": q["kc_id"],
            "prompt": q["prompt"],
            "qtype": q["qtype"],
        },
    )
    r = (
        await db.execute(
            text(
                f"SELECT {_COLS} FROM question_bookmarks "
                "WHERE student_id = :sid AND source = :src AND question_ref = :ref"
            ),
            {"sid": student_id, "src": source, "ref": question_id},
        )
    ).first()
    return _row(r) if r is not None else None


async def remove_bookmark(
    db: AsyncSession, student_id: uuid.UUID, bookmark_id: uuid.UUID
) -> bool:
    """仅删本人的收藏；非本人/不存在 → False（路由 404，不泄露存在性）。"""
    res = await db.execute(
        text("DELETE FROM question_bookmarks WHERE id = :id AND student_id = :sid"),
        {"id": bookmark_id, "sid": student_id},
    )
    return bool(getattr(res, "rowcount", 0))


async def list_bookmarks(
    db: AsyncSession, student_id: uuid.UUID, *, limit: int = 100
) -> list[dict]:
    rows = (
        await db.execute(
            text(
                f"SELECT {_COLS} FROM question_bookmarks WHERE student_id = :sid "
                "ORDER BY created_at DESC LIMIT :lim"
            ),
            {"sid": student_id, "lim": limit},
        )
    ).all()
    return [_row(r) for r in rows]
