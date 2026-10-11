"""practice_queue_service — Studio /practice 的只读练习队列（对标 DeepTutor Practice）。

只读投影，零写入：
- due：该学生 FSRS 已到期的 KC（kc_mastery.fsrs_card_json['due'] ≤ now），最久逾期在前；
- upcoming：尚未到期、最近要到期的 KC；
- wrong_questions：学生本人的错题（按题干去重计 wrong_count），**不含参考答案**；
  bookmarked 标记该错题是否已收藏；
- bookmarks：学生本人收藏（☆）的题（题干快照 + KC，**不含参考答案**）。

练习本身不在这里：Studio 对每个到期 KC 走既有 RequestQuestion → SubmitAnswer
（verdict_guard → process_interaction）这一条唯一受守卫的掌握度写入路径，答题后
FSRS 由内核重排，该 KC 自然离开 due。本模块不判分、不写掌握度、不出题。

红线：参考答案（correct_answer / expected）永不出现在返回体——Studio 前端结构上
不接触答案（见 apps/mneme-studio/lib/mcp.ts 头注）。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.models import KCMastery, KnowledgeUnit, WrongQuestion
from services.progress_assembler import _due_unix


def _iso_from_unix(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


async def practice_queue(
    db: AsyncSession,
    student_id: uuid.UUID,
    *,
    now: Optional[datetime] = None,
    upcoming_limit: int = 10,
    wrong_limit: int = 50,
    bookmark_limit: int = 100,
) -> dict:
    now_ts = (now or datetime.now(timezone.utc)).timestamp()

    masteries = (
        (
            await db.execute(
                select(KCMastery.knowledge_point, KCMastery.fsrs_card_json).where(
                    KCMastery.student_id == student_id,
                    KCMastery.fsrs_card_json.is_not(None),
                )
            )
        )
        .all()
    )
    schedule: list[tuple[str, float]] = []
    for kc, card in masteries:
        due_ts = _due_unix(card)
        if due_ts is not None:
            schedule.append((kc, due_ts))

    wq_rows = (
        (
            await db.execute(
                select(WrongQuestion)
                .where(WrongQuestion.student_id == student_id)
                .order_by(WrongQuestion.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    # 按题干去重（同 error-journal 口径）：同一题错多次合并，保留最新一次
    deduped: dict[str, dict[str, Any]] = {}
    for r in wq_rows:
        key = (r.question_text or "").strip() or str(r.id)
        if key in deduped:
            deduped[key]["wrong_count"] += 1
            continue
        kc = next(iter(r.knowledge_points), None) if r.knowledge_points else None
        text = r.question_text or ""
        has_image = bool(r.needs_image) or "<ImageHere>" in text
        deduped[key] = {
            "id": str(r.id),
            "ku_id": kc,
            "question_text": text,
            "has_image": has_image,
            "wrong_count": 1,
            "last_wrong_at": r.created_at.isoformat() if r.created_at else None,
        }
    wrong = list(deduped.values())

    from services.bookmark_service import list_bookmarks

    bookmarks = await list_bookmarks(db, student_id, limit=bookmark_limit)
    bookmarked_wq = {b["wrong_question_id"] for b in bookmarks if b["wrong_question_id"]}

    kc_ids = (
        {kc for kc, _ in schedule}
        | {w["ku_id"] for w in wrong if w["ku_id"]}
        | {b["kc_id"] for b in bookmarks if b["kc_id"]}
    )
    names: dict[str, str] = {}
    if kc_ids:
        names = {
            kid: nm
            for kid, nm in (
                await db.execute(
                    select(KnowledgeUnit.id, KnowledgeUnit.name).where(
                        KnowledgeUnit.id.in_(kc_ids)
                    )
                )
            ).all()
        }

    wrong_by_kc: dict[str, list[dict[str, Any]]] = {}
    for w in wrong:
        if w["ku_id"]:
            wrong_by_kc.setdefault(w["ku_id"], []).append(w)

    due_kcs = {kc for kc, ts in schedule if ts <= now_ts}

    def _kc_entry(kc: str, due_ts: float) -> dict[str, Any]:
        ws = wrong_by_kc.get(kc, [])
        sample = next((w for w in ws if not w["has_image"]), None)
        return {
            "kc_id": kc,
            "name": names.get(kc, kc),
            "due_at": _iso_from_unix(due_ts),
            "overdue_hours": round(max(now_ts - due_ts, 0.0) / 3600.0, 1),
            "wrong_count": sum(w["wrong_count"] for w in ws),
            "sample_wrong_question": sample["question_text"] if sample else None,
        }

    due = [
        _kc_entry(kc, ts)
        for kc, ts in sorted((s for s in schedule if s[1] <= now_ts), key=lambda s: s[1])
    ]
    upcoming = [
        _kc_entry(kc, ts)
        for kc, ts in sorted((s for s in schedule if s[1] > now_ts), key=lambda s: s[1])[
            :upcoming_limit
        ]
    ]
    return {
        "student_id": str(student_id),
        "due_count": len(due),
        "due": due,
        "upcoming": upcoming,
        "wrong_questions": [
            {
                **w,
                "ku_name": names.get(w["ku_id"], w["ku_id"]) if w["ku_id"] else None,
                "kc_due": w["ku_id"] in due_kcs,
                "bookmarked": w["id"] in bookmarked_wq,
            }
            for w in wrong[:wrong_limit]
        ],
        "bookmarks": [
            {
                "id": b["id"],
                "source": b["source"],
                "question_id": b["question_id"],
                "kc_id": b["kc_id"],
                "kc_name": names.get(b["kc_id"], b["kc_id"]) if b["kc_id"] else None,
                "prompt": b["prompt"],
                "qtype": b["qtype"],
                "created_at": b["created_at"],
                "kc_due": b["kc_id"] in due_kcs if b["kc_id"] else False,
            }
            for b in bookmarks
        ],
    }
