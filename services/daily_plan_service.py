"""
daily_plan_service.py — 每日计划规则引擎

3O 边界判断：此调度逻辑是纯业务排序，目前只服务于 Mneme；
没有跨产品复用需求，且规则较简单（硬编码优先级，无复杂状态机），
因此放在服务层实现，而非提升为 omodul。
如果未来多产品需要同一调度能力，再上移主库。

四优先级：
  P1 FSRS到期复习   — kc_mastery 中 fsrs_card_json 已到期
  P2 错题巩固       — wrong_questions 中未掌握的错题
  P3 薄弱知识点     — kc_mastery 中 p_mastery < 0.6
  P4 新知识点学习   — knowledge_units 中未出现在 kc_mastery 的 KU，
                      且其 prerequisites 均已掌握
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from oprim import due_compute
from services.models import KCMastery, KnowledgeUnit, Textbook, WrongQuestion

# ── 常量 ────────────────────────────────────────────────────────────────────

MASTERY_THRESHOLD      = 0.6   # p_mastery 低于此值视为薄弱
MINUTES_PER_REVIEW_KU  = 5
MINUTES_PER_WQ         = 5
MINUTES_PER_WEAK_KU    = 15
MINUTES_PER_NEW_KU     = 20

ALL_SUBJECTS = ["math", "physics", "english", "chinese"]

# GDMATH-* KC 前缀全部属于数学
_GDMATH_PREFIX = "GDMATH-"


def _kc_to_subject(kp: str, ku_subject_map: dict[str, str]) -> str:
    """将 knowledge_point 字符串转换为科目名。"""
    if kp in ku_subject_map:
        return ku_subject_map[kp]
    if kp.startswith(_GDMATH_PREFIX):
        return "math"
    return "math"  # 保守默认


# ── 核心入口 ─────────────────────────────────────────────────────────────────

async def build_daily_plan(
    db: AsyncSession,
    student_id: uuid.UUID,
    subject: Optional[str] = None,
    now: Optional[datetime] = None,
) -> dict:
    """
    生成该学生的每日计划任务列表。

    subject=None  → 所有科目混排（首页）
    subject=xxx   → 单科过滤（学科页）
    """
    if now is None:
        now = datetime.now(timezone.utc)

    # ── 1. 拉取该学生所有 kc_mastery ──────────────────────────────────────
    masteries: list[KCMastery] = list(
        (await db.execute(
            select(KCMastery).where(KCMastery.student_id == student_id)
        )).scalars().all()
    )

    # ── 2. 拉取所有 knowledge_units（已导入的）及其 subject 映射 ──────────
    ku_rows: list[KnowledgeUnit] = list(
        (await db.execute(select(KnowledgeUnit))).scalars().all()
    )
    # KU ID → Textbook，需要再查 textbooks
    tb_ids = {ku.textbook_id for ku in ku_rows}
    tb_map: dict[str, Textbook] = {}
    if tb_ids:
        tb_rows = list(
            (await db.execute(
                select(Textbook).where(Textbook.id.in_(tb_ids))
            )).scalars().all()
        )
        tb_map = {tb.id: tb for tb in tb_rows}

    # KU ID → subject 映射（供 P1/P3 从 kc_mastery.knowledge_point 反查科目）
    ku_subject_map: dict[str, str] = {}
    for ku in ku_rows:
        tb = tb_map.get(ku.textbook_id)
        if tb:
            ku_subject_map[ku.id] = tb.subject

    # ── 3. 已掌握的 knowledge_point 集合（p_mastery >= threshold）──────────
    #    用于 P4 前置检查
    mastered_kp_set: set[str] = {
        m.knowledge_point for m in masteries
        if (m.p_mastery or 0.0) >= MASTERY_THRESHOLD
    }
    # 已"接触过"的 kp（不论掌握度）
    known_kp_set: set[str] = {m.knowledge_point for m in masteries}

    # ── 4. 错题（P2）──────────────────────────────────────────────────────
    wq_stmt = select(WrongQuestion).where(WrongQuestion.student_id == student_id)
    if subject:
        wq_stmt = wq_stmt.where(WrongQuestion.subject == subject)
    wq_list: list[WrongQuestion] = list(
        (await db.execute(wq_stmt)).scalars().all()
    )

    # ── 5. 生成任务 ────────────────────────────────────────────────────────
    tasks: list[dict] = []

    # ── P1: FSRS 到期复习 ──────────────────────────────────────────────────
    due_by_subject: dict[str, list[str]] = {}
    for m in masteries:
        if not m.fsrs_card_json:
            continue
        subj = _kc_to_subject(m.knowledge_point, ku_subject_map)
        if subject and subj != subject:
            continue
        if due_compute(card_dict=m.fsrs_card_json, now=now):
            due_by_subject.setdefault(subj, []).append(m.knowledge_point)

    for subj, kp_ids in due_by_subject.items():
        n = len(kp_ids)
        tasks.append({
            "type": "review",
            "title": f"复习{n}个到期知识点",
            "subject": subj,
            "ku_ids": kp_ids,
            "priority": 1,
            "reason": "遗忘曲线临界，该复习了",
            "estimated_minutes": n * MINUTES_PER_REVIEW_KU,
        })

    # ── P2: 错题巩固 ────────────────────────────────────────────────────────
    if wq_list:
        wq_by_subject: dict[str, list] = {}
        for wq in wq_list:
            s = wq.subject or "math"
            if subject and s != subject:
                continue
            wq_by_subject.setdefault(s, []).append(str(wq.id))

        for subj, wq_ids in wq_by_subject.items():
            n = len(wq_ids)
            tasks.append({
                "type": "error_review",
                "title": f"重做{n}道错题",
                "subject": subj,
                "ku_ids": [],
                "priority": 2,
                "reason": "错题待巩固",
                "estimated_minutes": n * MINUTES_PER_WQ,
            })

    # ── P3: 薄弱知识点 ─────────────────────────────────────────────────────
    weak_by_subject: dict[str, list[str]] = {}
    for m in masteries:
        if (m.p_mastery or 0.0) >= MASTERY_THRESHOLD:
            continue
        subj = _kc_to_subject(m.knowledge_point, ku_subject_map)
        if subject and subj != subject:
            continue
        weak_by_subject.setdefault(subj, []).append(m.knowledge_point)

    for subj, kp_ids in weak_by_subject.items():
        n = len(kp_ids)
        tasks.append({
            "type": "weak_practice",
            "title": f"专项突破：{n}个薄弱知识点",
            "subject": subj,
            "ku_ids": kp_ids,
            "priority": 3,
            "reason": f"掌握度低于{int(MASTERY_THRESHOLD*100)}%",
            "estimated_minutes": min(n, 3) * MINUTES_PER_WEAK_KU,
        })

    # ── P4: 新知识点（按科目过滤，遵守 prerequisites）────────────────────
    new_by_subject: dict[str, list[KnowledgeUnit]] = {}
    for ku in ku_rows:
        if ku.id in known_kp_set:
            continue  # 已接触过
        tb = tb_map.get(ku.textbook_id)
        if not tb:
            continue
        subj = tb.subject
        if subject and subj != subject:
            continue
        # 检查前置：所有 prerequisites 均已掌握（在 mastered_kp_set 中）
        prereqs: list[str] = ku.prerequisites or []
        if any(p not in mastered_kp_set for p in prereqs):
            continue
        new_by_subject.setdefault(subj, []).append(ku)

    for subj, kus in new_by_subject.items():
        # 按 difficulty 升序，先推简单的
        kus_sorted = sorted(kus, key=lambda k: k.difficulty)
        ku_ids = [k.id for k in kus_sorted]
        n = len(ku_ids)
        tasks.append({
            "type": "new_learn",
            "title": f"学习{n}个新知识点",
            "subject": subj,
            "ku_ids": ku_ids,
            "priority": 4,
            "reason": "按课程进度，前置已掌握",
            "estimated_minutes": min(n, 2) * MINUTES_PER_NEW_KU,
        })

    # ── 5.5 交错练习队列（item 8）：把"到期(P1)+薄弱(P3)"的 KC 用 interleave_select
    #        排成相邻 KC 不同的检索序列（交错优于阻塞式同 KC 连练，利于迁移与长期保持）。
    interleaved_queue = _build_interleaved_queue(
        masteries, due_by_subject, weak_by_subject, ku_subject_map,
        {ku.id: ku.difficulty for ku in ku_rows},
    )

    # ── 6. 排序：priority ASC，同 priority 按科目固定顺序 ─────────────────
    subject_order = {s: i for i, s in enumerate(ALL_SUBJECTS)}
    tasks.sort(key=lambda t: (t["priority"], subject_order.get(t["subject"], 99)))

    # ── 7. subjects_summary ────────────────────────────────────────────────
    summary_map: dict[str, dict] = {}
    for t in tasks:
        s = t["subject"]
        if s not in summary_map:
            summary_map[s] = {"subject": s, "task_count": 0, "estimated_minutes": 0}
        summary_map[s]["task_count"] += 1
        summary_map[s]["estimated_minutes"] += t["estimated_minutes"]

    subjects_summary = sorted(
        summary_map.values(),
        key=lambda x: subject_order.get(x["subject"], 99),
    )

    return {
        "date":              now.date().isoformat(),
        "exam_countdown_days": None,  # TODO: 待 users 表添加 exam_date 字段
        "subjects_summary":  subjects_summary,
        "tasks":             tasks,
        "interleaved_queue": interleaved_queue,
    }


def _build_interleaved_queue(
    masteries: list[KCMastery],
    due_by_subject: dict[str, list[str]],
    weak_by_subject: dict[str, list[str]],
    ku_subject_map: dict[str, str],
    ku_difficulty_map: dict[str, float],
) -> list[dict]:
    """把到期+薄弱 KC 交错成相邻不同 KC 的练习序列。<2 个不同 KC 时原样返回（不交错）。"""
    from oskill.interleave_select import QuestionItem, interleave_select

    mastery_map = {m.knowledge_point: (m.p_mastery or 0.0) for m in masteries}
    # kc → (subject, source)；到期优先于薄弱
    pool: dict[str, tuple[str, str]] = {}
    for subj, kcs in weak_by_subject.items():
        for kc in kcs:
            pool[kc] = (subj, "weak")
    for subj, kcs in due_by_subject.items():
        for kc in kcs:
            pool[kc] = (subj, "review")  # 到期覆盖薄弱标注

    if not pool:
        return []
    items = [
        QuestionItem(
            question_id=kc, kc_id=kc,
            difficulty=float(ku_difficulty_map.get(kc, 0.5)),
            mastery=float(mastery_map.get(kc, 0.5)),
        )
        for kc in pool
    ]
    if len({it.kc_id for it in items}) < 2:
        ordered = items  # 不足 2 个不同 KC，无法交错
    else:
        ordered = interleave_select(items).selected
    return [
        {"kc_id": it.kc_id, "subject": pool[it.kc_id][0], "source": pool[it.kc_id][1]}
        for it in ordered
    ]
