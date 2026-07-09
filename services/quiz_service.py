"""quiz_service.py — T.8 周期限时小测（检索检查点）

3O 边界：编排 oskill.interleave_select + oprim.due_compute/answer_judge + 持久化，
与 review_service/daily_plan_service 同级的服务层业务事务，不提升为 omodul。

设计：每 _QUIZ_CADENCE_DAYS 天（不是每天）生成一次限时小测——5 道题（不足则如实少给，
不硬凑），取自到期(FSRS due)优先、薄弱(p_mastery<GATE)兜底的 KC 池，交错排布防连续
同 KC。提交后判分回写 BKT/FSRS（source=quiz）；答错的 KC 不需要额外"生成复习任务"——
FSRS Again 评级本身就会顺延到近期 due，自然进入下一次到期复习队列（同一套机制，不重复
造轮子）。自由作答判不出对错（judge_answer→unsure）时不喂 BKT（宁可不确定不误判，
同 review_service 既有原则），但计入小测得分为"未确认"。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from oprim import due_compute
from oprim.answer_judge import judge_answer
from services.learner_model import GATE
from services.models import KCMastery, TimedQuiz, WrongQuestion

_QUIZ_CADENCE_DAYS = 3  # 每 3 天一次限时小测（检索检查点，非每日任务）
_MAX_ITEMS = 5
_SECONDS_PER_ITEM = 60  # 限时预算：每题 1 分钟


async def get_or_create_due_quiz(
    db: AsyncSession, student_id: uuid.UUID, *, now: Optional[datetime] = None
) -> dict:
    """检查是否到期该做小测；到期则现场生成一份（不落答案，只发题面）。"""
    now = now or datetime.now(timezone.utc)

    last = (
        await db.execute(
            select(TimedQuiz.created_at)
            .where(TimedQuiz.student_id == student_id)
            .order_by(TimedQuiz.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    if last is not None:
        next_due = last + timedelta(days=_QUIZ_CADENCE_DAYS)
        if now < next_due:
            return {"due": False, "next_due_date": next_due.date().isoformat()}

    masteries = (
        (await db.execute(select(KCMastery).where(KCMastery.student_id == student_id)))
        .scalars()
        .all()
    )

    due_kcs = [
        m.knowledge_point
        for m in masteries
        if m.fsrs_card_json and due_compute(card_dict=m.fsrs_card_json, now=now)
    ]
    weak_kcs = [
        m.knowledge_point
        for m in masteries
        if (m.p_mastery or 0.0) < GATE and m.knowledge_point not in due_kcs
    ]
    # 到期优先，薄弱兜底，去重保序
    kc_pool = list(dict.fromkeys(due_kcs + weak_kcs))[:_MAX_ITEMS]

    if not kc_pool:
        return {"due": False, "reason": "暂无到期/薄弱知识点，不生成小测"}

    items: list[dict] = []
    for kc_id in kc_pool:
        wq = (
            await db.execute(
                select(WrongQuestion)
                .where(WrongQuestion.knowledge_points.has_key(kc_id))
                .where(WrongQuestion.correct_answer.is_not(None))
                .order_by(WrongQuestion.student_id.is_(None).desc())  # 公共题库优先
                .limit(1)
            )
        ).scalar_one_or_none()
        if wq is None:
            continue
        items.append(
            {
                "ku_id": kc_id,
                "question_id": str(wq.id),
                "question_text": wq.question_text,
            }
        )

    if not items:
        return {"due": False, "reason": "到期/薄弱知识点暂无可用题目，不生成小测"}

    # 交错：<2 个不同 KC 时无法交错，原样返回（同 daily_plan_service 既有约定）
    if len({it["ku_id"] for it in items}) >= 2:
        from oskill.interleave_select import QuestionItem, interleave_select

        mastery_map = {m.knowledge_point: (m.p_mastery or 0.5) for m in masteries}
        q_items = [
            QuestionItem(
                question_id=it["question_id"],
                kc_id=it["ku_id"],
                difficulty=0.5,
                mastery=mastery_map.get(it["ku_id"], 0.5),
            )
            for it in items
        ]
        ordered_ids = [q.question_id for q in interleave_select(q_items).selected]
        by_qid = {it["question_id"]: it for it in items}
        items = [by_qid[qid] for qid in ordered_ids if qid in by_qid]

    quiz_id = uuid.uuid4()
    time_limit_seconds = len(items) * _SECONDS_PER_ITEM
    db.add(
        TimedQuiz(
            id=quiz_id,
            student_id=student_id,
            items=items,
            time_limit_seconds=time_limit_seconds,
        )
    )
    await db.commit()
    # 注：commit 后不再读 ORM 对象属性——obase.db.SessionLocal 用默认
    # expire_on_commit=True，commit 后属性已过期，隐式惰性刷新在 AsyncSession
    # 下会触发 MissingGreenlet；上面已用本地变量 quiz_id/time_limit_seconds，
    # 不需要读回对象。

    return {
        "due": True,
        "quiz_id": str(quiz_id),
        "time_limit_seconds": time_limit_seconds,
        "items": [
            {
                "ku_id": it["ku_id"],
                "question_id": it["question_id"],
                "question_text": it["question_text"],
            }
            for it in items
        ],
    }


async def submit_quiz(
    db: AsyncSession,
    student_id: uuid.UUID,
    quiz_id: uuid.UUID,
    answers: list[dict],
    time_spent_seconds: int,
) -> dict:
    """提交限时小测。answers: [{question_id, student_answer}]。

    判分回写 BKT/FSRS（source=quiz）；unsure（自由作答判不出对错）不喂 BKT，
    计小测分时按"未确认"处理（不算通过，也不算误判）。
    """
    quiz = (
        await db.execute(select(TimedQuiz).where(TimedQuiz.id == quiz_id))
    ).scalar_one_or_none()
    if quiz is None:
        return {"error": "quiz not found"}
    if quiz.student_id != student_id:
        return {"error": "not your quiz"}
    if quiz.submitted_at is not None:
        return {"error": "already submitted"}

    answer_map = {a["question_id"]: a.get("student_answer", "") for a in answers}
    items: list[dict] = quiz.items or []
    per_item_seconds = time_spent_seconds // len(items) if items else 0

    from services.cognitive_service import process_interaction

    results: list[dict] = []
    correct_count = 0
    for it in items:
        qid = it["question_id"]
        kc_id = it["ku_id"]
        wq = (
            await db.execute(select(WrongQuestion).where(WrongQuestion.id == qid))
        ).scalar_one_or_none()
        correct_answer = (wq.correct_answer or "") if wq else ""
        student_answer = answer_map.get(qid, "")
        verdict = judge_answer(student_answer, correct_answer).get("verdict", "unsure")

        if verdict in ("correct", "wrong"):
            await process_interaction(
                db,
                student_id=student_id,
                kc_id=kc_id,
                is_correct=(verdict == "correct"),
                question_type="quiz",
                question_id=uuid.UUID(qid) if wq else None,
                source="quiz",
                time_spent_seconds=per_item_seconds,
            )
            if verdict == "correct":
                correct_count += 1

        results.append({"ku_id": kc_id, "question_id": qid, "verdict": verdict})

    score = round(correct_count / len(items), 4) if items else 0.0
    now = datetime.now(timezone.utc)
    quiz.submitted_at = now
    quiz.time_spent_seconds = time_spent_seconds
    quiz.score = score
    quiz.results = results
    await db.commit()

    failed_kcs = [r["ku_id"] for r in results if r["verdict"] == "wrong"]

    return {
        "quiz_id": str(quiz_id),
        "score": score,
        "results": results,
        "failed_kcs": failed_kcs,
    }
