"""10 分钟错题复习（/v1/review/today）。

错题本 = 该生 wrong_questions 行（任何来源答错自动入本 + 学生手动加入），按 FSRS 到期排程。
复用既有 FSRS 引擎（oprim.fsrs_engine，py-fsrs）与 wrong_questions 上早已存在的
fsrs_card_json / fsrs_due / fsrs_state 列——不另建调度器。

选题：
1. 已到期（fsrs_due <= now）按到期先后；同到期按所属 KC 掌握度（kc_mastery.p_learned 低者优先）；
2. 从未复习（fsrs_due 为空）的新错题；
3. 还有时间预算就补「三天内到期且 KC 薄弱（p<0.6）」的题。
按每题预计用时累加到 ~10 分钟（600s），最多 10 题。

判分（确定性优先）：选择题 → answer_judge；数学 → math_grade（sympy 等价）+ 数值容差；
英语 → 缩写感知等价；仍判不了且 LLM 可用 → LLM 判分（短超时）；否则学生对照答案自评。

毕业：连续答对 3 次且最近一次答对时 FSRS 间隔 ≥ 7 天（或连续答对 4 次）→ graduated_at，不再出现。

变式（services.ask_kernels.variants）：能被精确内核解出的错题，第一次复习出原题，之后的复习出
“同类型、换数字”的变式题（种子 = 错题 id + 已复习次数，确定性，作答时用同一种子重建并用内核判分）。
会话里的变式题 item 带 variant=True 与 original_text；作答接口不变（仍按 item_id 提交）。
"""

from __future__ import annotations

import asyncio
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional
from dataclasses import dataclass

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from services.logging_config import logger
from services.models import KCMastery, WrongQuestion

VARIANT_SUBJECTS = {None, "", "math", "数学", "physics", "物理", "chemistry", "化学"}

SESSION_BUDGET_SECONDS = 600
MAX_ITEMS = 10
GRADUATE_STREAK = 3
GRADUATE_STREAK_HARD = 4
GRADUATE_MIN_INTERVAL_DAYS = 7.0
WEAK_P = 0.6

_CHOICE = re.compile(r"^\s*[A-Da-d](\s*[,，、]?\s*[A-Da-d]){0,3}\s*$")
_NUMERIC = re.compile(r"^[\s0-9a-zA-Z+\-*/^().=√π,，;；、<>≤≥xX²³·÷×$\\{}]*$")
_LONG_MARKERS = re.compile(r"解析|见解析|【解|证明|\(1\)|（1）")


def answer_type(correct_answer: Optional[str], subject: Optional[str]) -> str:
    """numeric | choice | text | self（无法确定性判分 → 自评）。"""
    ans = (correct_answer or "").strip()
    if not ans or len(ans) > 60 or _LONG_MARKERS.search(ans):
        return "self"
    if _CHOICE.match(ans):
        return "choice"
    if subject in (None, "", "math", "数学", "physics", "物理") and _NUMERIC.match(ans) and re.search(r"\d", ans):
        return "numeric"
    if len(ans) <= 40:
        return "text"
    return "self"


def estimate_seconds(question_text: Optional[str], atype: str) -> int:
    base = {"choice": 45, "numeric": 75, "text": 60, "self": 90}.get(atype, 75)
    extra = max(0, len(question_text or "") - 60) // 10
    return int(min(180, base + extra))


def _num(s: str) -> Optional[float]:
    t = (s or "").strip().replace("，", ",").replace(" ", "")
    t = re.sub(r"^[a-zA-Z]\w*=", "", t)
    try:
        if re.fullmatch(r"-?\d+(\.\d+)?", t):
            return float(t)
        if re.fullmatch(r"-?\d+/\d+", t):
            a, b = t.split("/")
            return float(a) / float(b) if float(b) != 0 else None
        if re.fullmatch(r"-?\d+(\.\d+)?%", t):
            return float(t[:-1]) / 100.0
    except ValueError:
        return None
    return None


def grade_deterministic(answer: str, expected: str, subject: Optional[str]) -> tuple[Optional[bool], str]:
    """(is_correct | None=判不了, grader)。grader ∈ {kernel, rule}。"""
    a = (answer or "").strip()
    e = (expected or "").strip()
    if not a:
        return False, "rule"  # 空答 = 不会（看答案）
    if not e:
        return None, "none"
    atype = answer_type(e, subject)
    if atype == "self":
        return None, "none"
    if atype == "choice":
        from oprim.answer_judge import judge_answer

        v = judge_answer(a, e)["verdict"]
        return (None, "none") if v == "unsure" else (v == "correct", "rule")
    # 数值容差：两边都是纯数（含分数/百分数）→ 相对误差 1e-3
    na, ne = _num(a), _num(e)
    if na is not None and ne is not None:
        return abs(na - ne) <= max(1e-9, 1e-3 * max(1.0, abs(ne))), "kernel"
    if atype == "numeric":
        from services.math_grade import grade_math_detailed

        g = grade_math_detailed(a, e)
        if g.method == "sympy":
            return g.is_correct, "kernel"
        if g.is_correct:
            return True, "rule"
    from services.english_check_service import english_equivalent_answer, looks_english

    if looks_english(e):
        if english_equivalent_answer(a, e):
            return True, "kernel"
        norm = lambda s: re.sub(r"[\s.!?,;:'’\"]+", " ", s.lower()).strip()  # noqa: E731
        return norm(a) == norm(e), "rule"
    from oprim.answer_judge import judge_answer

    v = judge_answer(a, e)["verdict"]
    if v == "correct":
        return True, "rule"
    if atype == "numeric" and v == "wrong":
        return False, "rule"
    return None, "none"


async def grade_with_llm(question: str, answer: str, expected: str, timeout: float = 12.0) -> Optional[bool]:
    """判不了的题：问 LLM 是否等价（只输出 yes/no）。不可用 → None（交学生自评）。"""
    from services.photo_ask_service import _llm_call

    raw = await _llm_call(
        system="你是严格的阅卷老师。判断学生答案与标准答案是否表达同一个结果。只回答 yes 或 no。",
        user=f"题目：{question[:1500]}\n标准答案：{expected[:500]}\n学生答案：{answer[:500]}",
        max_tokens=5,
        timeout=timeout,
        json_mode=False,
    )
    if not raw:
        return None
    r = raw.strip().lower()
    if r.startswith("yes") or r.startswith("是"):
        return True
    if r.startswith("no") or r.startswith("否") or r.startswith("不"):
        return False
    return None


def _variant_seed(item_id: uuid.UUID, review_count: int) -> int:
    return (int(item_id.hex[:8], 16) ^ (int(review_count) * 7919)) & 0x7FFFFFFF


_VARIANT_CACHE: dict[tuple[str, int], Optional[dict]] = {}


def variant_for(question_text: Optional[str], subject: Optional[str], item_id: uuid.UUID, review_count: int) -> Optional[dict]:
    """第 2 次及以后的复习：返回 {text, kernel, solution}；第一次（review_count=0）或做不出干净变式 → None。"""
    if review_count < 1 or not question_text or subject not in VARIANT_SUBJECTS:
        return None
    seed = _variant_seed(item_id, review_count)
    key = (question_text, seed)
    if key in _VARIANT_CACHE:
        return _VARIANT_CACHE[key]
    try:
        from services.ask_kernels.variants import make_variant

        v = make_variant(question_text, seed, subject=subject, budget_s=1.5)
    except Exception as exc:  # noqa: BLE001
        logger.info("wrongbook variant failed: %s", type(exc).__name__)
        v = None
    if len(_VARIANT_CACHE) > 512:
        _VARIANT_CACHE.clear()
    _VARIANT_CACHE[key] = v
    return v


def _variant_answer_type(kind: str) -> str:
    return "numeric" if kind in ("num", "nums") else "text"


def _first_kc(wq: WrongQuestion) -> Optional[str]:
    kp = wq.knowledge_points or {}
    for k in kp.keys() if isinstance(kp, dict) else []:
        if k and k != "unknown":
            return str(k)
    return None


async def build_today_session(db: AsyncSession, student_id: uuid.UUID, *, now: Optional[datetime] = None) -> dict:
    now = now or datetime.now(timezone.utc)
    base = (
        select(WrongQuestion)
        .where(
            WrongQuestion.student_id == student_id,
            WrongQuestion.graduated_at.is_(None),
            WrongQuestion.question_text.isnot(None),
            WrongQuestion.question_text != "",
        )
    )
    due_rows = (
        await db.execute(
            base.where(WrongQuestion.fsrs_due <= now).order_by(WrongQuestion.fsrs_due.asc()).limit(200)
        )
    ).scalars().all()
    new_rows = (
        await db.execute(
            base.where(WrongQuestion.fsrs_due.is_(None)).order_by(WrongQuestion.created_at.desc()).limit(200)
        )
    ).scalars().all()
    soon_rows = (
        await db.execute(
            base.where(WrongQuestion.fsrs_due > now, WrongQuestion.fsrs_due <= now + timedelta(days=3))
            .order_by(WrongQuestion.fsrs_due.asc())
            .limit(50)
        )
    ).scalars().all()

    kcs = {k for r in (*due_rows, *new_rows, *soon_rows) if (k := _first_kc(r))}
    p_map: dict[str, float] = {}
    if kcs:
        for kp, p in (
            await db.execute(
                select(KCMastery.knowledge_point, KCMastery.p_mastery).where(
                    KCMastery.student_id == student_id, KCMastery.knowledge_point.in_(kcs)
                )
            )
        ).all():
            p_map[kp] = float(p) if p is not None else 0.5

    def weakness(r: WrongQuestion) -> float:
        k = _first_kc(r)
        return p_map.get(k, 0.5) if k else 0.5

    due_sorted = sorted(due_rows, key=lambda r: (r.fsrs_due.date() if r.fsrs_due else now.date(), weakness(r)))
    new_sorted = sorted(new_rows, key=lambda r: weakness(r))
    weak_soon = [r for r in soon_rows if _first_kc(r) and weakness(r) < WEAK_P]

    picked: list[dict] = []
    seen: set[str] = set()
    used = 0
    for r in [*due_sorted, *new_sorted, *weak_soon]:
        key = re.sub(r"\s+", "", r.question_text or "")
        if str(r.id) in seen or key in seen:
            continue
        atype = answer_type(r.correct_answer, r.subject)
        est = estimate_seconds(r.question_text, atype)
        if picked and (used + est > SESSION_BUDGET_SECONDS + 30 or len(picked) >= MAX_ITEMS):
            break
        seen.add(str(r.id))
        seen.add(key)
        used += est
        picked.append(
            {
                "item_id": str(r.id),
                "subject": r.subject,
                "question_text": r.question_text,
                "has_image": bool(r.image_key),
                "image_record_id": str(r.id) if r.image_key else None,
                "answer_type": atype,
                "est_seconds": est,
                "review_count": int(r.review_count or 0),
                "variant": False,
                "_rc": int(r.review_count or 0),
                "_id": r.id,
            }
        )
    # 变式：第二次起出“换数字”的同类题（CPU 计算放线程，整体限时）
    import time as _time

    t_var = _time.monotonic()
    for item in picked:
        rc, rid = item.pop("_rc"), item.pop("_id")
        if rc < 1 or _time.monotonic() - t_var > 4.0:
            continue
        try:
            v = await asyncio.wait_for(
                asyncio.to_thread(variant_for, item["question_text"], item["subject"], rid, rc), timeout=2.5
            )
        except Exception:  # noqa: BLE001
            v = None
        if v is None:
            continue
        item.update(
            {
                "variant": True,
                "original_text": item["question_text"],
                "question_text": v["text"],
                "has_image": False,
                "image_record_id": None,
                "answer_type": _variant_answer_type(v["solution"].get("answer_kind", "num")),
            }
        )
    total_due = len(due_rows) + len(new_rows)
    return {
        "session_id": str(uuid.uuid4()),
        "budget_seconds": SESSION_BUDGET_SECONDS,
        "est_total_seconds": used,
        "total_due": total_due,
        "items": picked,
    }


def schedule_after_answer(wq: WrongQuestion, *, is_correct: bool, struggled: bool, now: datetime) -> dict:
    """FSRS 排程 + 毕业判定（纯函数式更新 wq 字段，不提交）。"""
    from obase.cognitive_types import fsrs_new_card
    from oprim.fsrs_engine import fsrs_map_rating, fsrs_review

    card = wq.fsrs_card_json or fsrs_new_card()
    rating = fsrs_map_rating(is_correct=is_correct, struggled=struggled)
    new_card = fsrs_review(card_dict=card, rating=rating, now=now)
    due_raw = new_card.get("due")
    due = datetime.fromisoformat(str(due_raw).replace("Z", "+00:00")) if due_raw else now + timedelta(days=1)
    wq.fsrs_card_json = new_card
    wq.fsrs_due = due
    wq.fsrs_state = str(new_card.get("state")) if new_card.get("state") is not None else None
    wq.review_count = int(wq.review_count or 0) + 1
    wq.review_correct_streak = int(wq.review_correct_streak or 0) + 1 if is_correct else 0
    wq.last_reviewed_at = now
    interval_days = (due - now).total_seconds() / 86400.0
    graduated = bool(
        is_correct
        and (
            (wq.review_correct_streak >= GRADUATE_STREAK and interval_days >= GRADUATE_MIN_INTERVAL_DAYS)
            or wq.review_correct_streak >= GRADUATE_STREAK_HARD
        )
    )
    if graduated:
        wq.graduated_at = now
    return {"next_due": due.isoformat(), "graduated": graduated, "interval_days": round(interval_days, 2)}


async def answer_item(
    db: AsyncSession,
    student_id: uuid.UUID,
    *,
    item_id: uuid.UUID,
    answer: str,
    duration_ms: Optional[int],
    self_grade: Optional[bool],
    session_id: Optional[str] = None,
    now: Optional[datetime] = None,
) -> Optional[dict]:
    """判分 → 排程 → 记录。题不存在/不属于该生 → None。"""
    now = now or datetime.now(timezone.utc)
    wq = await db.get(WrongQuestion, item_id)
    if wq is None or wq.student_id != student_id:
        return None
    expected = wq.correct_answer or ""
    question = wq.question_text or ""
    variant = await asyncio.to_thread(variant_for, question, wq.subject, wq.id, int(wq.review_count or 0))
    variant_steps: Optional[str] = None
    kernel_sol: Optional[dict] = variant["solution"] if variant else None
    if variant:
        question = variant["text"]
        expected = str(variant["solution"].get("answer") or "")
        variant_steps = "\n".join(str(x) for x in (variant["solution"].get("steps") or [])[:8])
    if self_grade is not None:
        is_correct: Optional[bool] = bool(self_grade)
        grader = "self"
    else:
        is_correct, grader = None, "none"
        if kernel_sol is None and (answer or "").strip() and answer_type(expected, wq.subject) != "choice":
            kernel_sol = await asyncio.to_thread(_kernel_solution, question, wq.subject)
        if kernel_sol is not None and (answer or "").strip():
            from services.ask_kernels.variants import grade_answer

            try:
                k = await asyncio.to_thread(
                    grade_answer,
                    answer,
                    str(kernel_sol.get("answer_value") or ""),
                    str(kernel_sol.get("answer_kind") or "num"),
                    str(kernel_sol.get("unit") or ""),
                )
            except Exception:  # noqa: BLE001
                k = None
            if k is not None:
                is_correct, grader = k, "kernel"
        if is_correct is None and not variant:
            is_correct, grader = grade_deterministic(answer, expected, wq.subject)
        if is_correct is None and expected and (answer or "").strip():
            llm = await grade_with_llm(question, answer, expected)
            if llm is not None:
                is_correct, grader = llm, "llm"
    if is_correct is None:
        return {
            "item_id": str(item_id),
            "is_correct": None,
            "needs_self_grade": True,
            "correct_answer": expected or None,
            "variant": bool(variant),
            "explanation": variant_steps or _explanation(wq),
            "grader": "none",
            "next_due": wq.fsrs_due.isoformat() if wq.fsrs_due else None,
            "graduated": False,
        }
    struggled = bool(duration_ms and duration_ms > 3 * 60 * 1000)
    sched = schedule_after_answer(wq, is_correct=is_correct, struggled=struggled, now=now)
    kc = _first_kc(wq)
    subject, kp = wq.subject, wq.knowledge_points
    image_key = wq.image_key if not variant else None
    wq_id = wq.id
    explanation = variant_steps or _explanation(wq)
    await db.commit()  # 默认 expire_on_commit：此后不再读 wq 属性（async 懒加载会炸）

    # BKT/FSRS 知识点真相源：有真实 KC 才写；失败不影响复习主流程。
    if kc:
        try:
            from services.cognitive_service import process_interaction

            await process_interaction(
                db,
                student_id=student_id,
                kc_id=kc,
                is_correct=is_correct,
                question_id=wq_id,
                source="review",
                time_spent_seconds=int(duration_ms / 1000) if duration_ms else None,
            )
            await db.commit()
        except Exception as exc:  # noqa: BLE001
            await db.rollback()
            logger.info("wrongbook review KC write skipped: %s", type(exc).__name__)

    from services.question_record_service import record_question

    await record_question(
        student_id=student_id,
        source="review",
        question_text=question,
        subject=subject,
        kc_ids=kp,
        question_ref=str(item_id),
        image_key=image_key,
        student_answer=answer,
        correct_answer=expected or None,
        is_correct=is_correct,
        grader=grader,
        duration_ms=duration_ms,
        wrong_question_id=item_id,
        meta={
            "session_id": session_id,
            "graduated": sched["graduated"],
            "next_due": sched["next_due"],
            **({"variant": True, "variant_kernel": variant["kernel"]} if variant else {}),
        },
    )
    return {
        "item_id": str(item_id),
        "is_correct": is_correct,
        "needs_self_grade": False,
        "variant": bool(variant),
        "correct_answer": expected or None,
        "explanation": explanation,
        "grader": grader,
        "next_due": sched["next_due"],
        "graduated": sched["graduated"],
    }


def _kernel_solution(question: str, subject: Optional[str]) -> Optional[dict]:
    """原题能被精确内核解出时，用内核答案判分（比字符串比对更稳）。"""
    try:
        from services.ask_kernels import solve_text

        sol = solve_text(question, subject, budget_s=2.0)
    except Exception:  # noqa: BLE001
        return None
    return sol.to_dict() if sol is not None else None


def _explanation(wq: WrongQuestion) -> Optional[str]:
    pa = wq.profiler_analysis if isinstance(wq.profiler_analysis, dict) else {}
    for key in ("explanation", "analysis", "solution", "解析"):
        v = pa.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()[:600]
    meta_steps = (wq.step_analysis or {}).get("solution_steps") if isinstance(wq.step_analysis, dict) else None
    if isinstance(meta_steps, list) and meta_steps:
        return "\n".join(str(s) for s in meta_steps[:6])
    return None


async def finish_session(
    db: AsyncSession,
    student_id: uuid.UUID,
    *,
    answered: int,
    correct: int,
    duration_seconds: Optional[int] = None,
    now: Optional[datetime] = None,
) -> dict:
    from zoneinfo import ZoneInfo

    from services.question_record_service import review_streak, today_review_stats

    now = now or datetime.now(timezone.utc)
    today = now.astimezone(ZoneInfo("Asia/Shanghai")).date()
    st = await review_streak(db, student_id=student_id, today=today)
    tstats = await today_review_stats(db, student_id=student_id, today=today)
    # 明天要复习：到明天（北京时间）结束前到期、未毕业的错题数（含今天没做完的）
    tomorrow_end = datetime(today.year, today.month, today.day, tzinfo=timezone.utc) + timedelta(days=2) - timedelta(hours=8)
    due_tomorrow = (
        await db.execute(
            select(func.count())
            .select_from(WrongQuestion)
            .where(
                WrongQuestion.student_id == student_id,
                WrongQuestion.graduated_at.is_(None),
                WrongQuestion.question_text.isnot(None),
                or_(WrongQuestion.fsrs_due.is_(None), WrongQuestion.fsrs_due < tomorrow_end),
            )
        )
    ).scalar_one()
    remaining = (
        await db.execute(
            select(WrongQuestion.id).where(
                WrongQuestion.student_id == student_id,
                WrongQuestion.graduated_at.is_(None),
                WrongQuestion.question_text.isnot(None),
                or_(WrongQuestion.fsrs_due.is_(None), WrongQuestion.fsrs_due <= now),
            )
        )
    ).all()
    nxt = (
        await db.execute(
            select(WrongQuestion.fsrs_due)
            .where(
                WrongQuestion.student_id == student_id,
                WrongQuestion.graduated_at.is_(None),
                WrongQuestion.question_text.isnot(None),
                WrongQuestion.fsrs_due > now,
            )
            .order_by(WrongQuestion.fsrs_due.asc())
            .limit(1)
        )
    ).scalar_one_or_none()
    # 下次复习：还有到期没做完的 → now；否则取最早的未来到期时间，按北京时间给出 today/tomorrow/date
    tz = ZoneInfo("Asia/Shanghai")
    if remaining:
        next_kind: Optional[str] = "now"
    elif nxt is not None:
        d = (nxt if nxt.tzinfo else nxt.replace(tzinfo=timezone.utc)).astimezone(tz).date()
        next_kind = "today" if d == today else ("tomorrow" if d == today + timedelta(days=1) else "later")
    else:
        next_kind = None
    if answered <= 0:
        msg = "今天还没开始复习哦，花 10 分钟把错题过一遍吧。"
    elif correct == answered:
        msg = f"太棒了，本次 {answered} 道全做对！这些错题你已经掌握得越来越牢了 🎉"
    elif correct * 2 >= answered:
        msg = f"做对了 {correct}/{answered} 道，做错的题会更早再出现，帮你记牢。"
    else:
        msg = f"做对了 {correct}/{answered} 道。别灰心，错题多练几次就会了，明天它们会再来找你。"
    return {
        "streak": st["streak"],
        "longest_streak": st["longest_streak"],
        "remaining_due": len(remaining),
        "next_due_at": nxt.isoformat() if nxt else None,
        "next_due_kind": next_kind,
        "session_answered": answered,
        "session_correct": correct,
        "session_minutes": round(duration_seconds / 60, 1) if duration_seconds is not None else None,
        "due_tomorrow": int(due_tomorrow or 0),
        "today_answered": tstats["answered"],
        "today_correct": tstats["correct"],
        "today_accuracy": round(tstats["correct"] / tstats["answered"], 4) if tstats["answered"] else None,
        "today_minutes": round(tstats["duration_ms"] / 60000, 1),
        "message": msg,
    }


__all__ = [
    "answer_item",
    "answer_type",
    "build_today_session",
    "estimate_seconds",
    "finish_session",
    "grade_deterministic",
    "schedule_after_answer",
]
# ── Exam Cram 嫁接 2：错题优先重测队列 + 确定性小抄 ─────────────
# 接在 services/wrongbook_review_service.py 末尾（不改 build_today_session /
# schedule_after_answer / answer_item 的既有行为）。
#
# 分工（沿用仓内既定口径）：
# - FSRS 只管复测排期（wrong_questions.fsrs_due 由既有 oprim 引擎维护），
#   掌握判定仍走 BKT（answer_item 里的 process_interaction），本文件不写
#   任何掌握度字段。
# - “错次”取 question_records 里 is_correct=False 的记录数；错题本里的
#   每一行本身就代表至少一次答错，故下限为 1（无记录的老数据不判 0）。



@dataclass
class PriorityItem:
    item_id: str
    subject: Optional[str]
    question_text: str
    fsrs_due: Optional[datetime]
    error_count: int
    last_wrong_at: Optional[datetime]
    review_count: int
    kc: Optional[str]

    def to_dict(self) -> dict:
        return {
            "item_id": self.item_id,
            "subject": self.subject,
            "question_text": self.question_text,
            "fsrs_due": self.fsrs_due.isoformat() if self.fsrs_due else None,
            "error_count": self.error_count,
            "last_wrong_at": self.last_wrong_at.isoformat() if self.last_wrong_at else None,
            "review_count": self.review_count,
            "kc": self.kc,
        }


def rank_review_items(items: list[dict], *, now: datetime) -> list[dict]:
    """纯函数排序：到期 FSRS 项优先 → 错次多者 → 最近错者。

    items 每项含 fsrs_due（datetime 或 None）、error_count（int）、
    last_wrong_at（datetime 或 None）。返回新列表，不改入参顺序。
    - tier 0：已到期（fsrs_due <= now），按到期先后升序；
    - tier 1：其余，按 error_count 降序，再按 last_wrong_at 降序
      （无记录者视为最旧，排最后）。
    """
    due = []
    rest = []
    for it in items:
        if it.get("fsrs_due") is not None and it["fsrs_due"] <= now:
            due.append(it)
        else:
            rest.append(it)
    due.sort(key=lambda it: it["fsrs_due"])

    def _rest_key(it: dict) -> tuple:
        last = it.get("last_wrong_at")
        ts = last.timestamp() if last is not None else 0.0
        return (-int(it.get("error_count") or 0), -ts)

    rest.sort(key=_rest_key)
    return due + rest


async def build_priority_queue(
    db: AsyncSession,
    student_id: uuid.UUID,
    *,
    now: Optional[datetime] = None,
    limit: int = 50,
) -> dict:
    """未毕业错题的优先重测队列：只读排序，不出变式，不截会话预算，
    不改任何掌握度/排期字段。"""
    from services.models import QuestionRecord

    now = now or datetime.now(timezone.utc)
    rows = (
        await db.execute(
            select(WrongQuestion).where(
                WrongQuestion.student_id == student_id,
                WrongQuestion.graduated_at.is_(None),
                WrongQuestion.question_text.isnot(None),
                WrongQuestion.question_text != "",
            )
        )
    ).scalars().all()
    if not rows:
        return {"student_id": str(student_id), "total_open": 0, "items": []}
    ids = [r.id for r in rows]
    err_rows = (
        await db.execute(
            select(
                QuestionRecord.wrong_question_id,
                func.count(),
                func.max(QuestionRecord.created_at),
            ).where(
                QuestionRecord.student_id == student_id,
                QuestionRecord.wrong_question_id.in_(ids),
                QuestionRecord.is_correct.is_(False),
            ).group_by(QuestionRecord.wrong_question_id)
        )
    ).all()
    err_map: dict = {str(wqid): (int(cnt), last) for wqid, cnt, last in err_rows}
    items: list[dict] = []
    for r in rows:
        cnt, last = err_map.get(str(r.id), (0, None))
        items.append(
            {
                "item_id": str(r.id),
                "subject": r.subject,
                "question_text": r.question_text,
                "fsrs_due": r.fsrs_due,
                "error_count": max(1, cnt),
                "last_wrong_at": last,
                "review_count": int(r.review_count or 0),
                "kc": _first_kc(r),
            }
        )
    ranked = rank_review_items(items, now=now)
    return {
        "student_id": str(student_id),
        "total_open": len(ranked),
        "items": ranked[: max(0, int(limit))],
    }


def render_cheatsheet(groups: list[dict], *, student_label: str = "") -> str:
    """确定性小抄拼装：只拼资料原文与错题记录，缺项留空，绝不现编。

    groups 每项：kc、ku_name（或 None）、ku_description（或 None）、
    open_items（每项 question_text、error_type、review_count）。
    仓内目前没有“章节小结 / 困惑点”存储，故这两栏固定留空（暂无），
    不由 LLM 生成——有存储后再接。
    """
    lines = ["# 错题小抄"]
    if student_label:
        lines.append(f"\n学生：{student_label}")
    if not groups:
        lines.append("\n（暂无未关闭错题）")
        return "\n".join(lines) + "\n"
    for g in groups:
        lines.append(f"\n## {g.get('ku_name') or g.get('kc') or '未归类'}")
        if g.get("ku_description"):
            lines.append(f"\n资料原文：{g['ku_description']}")
        else:
            lines.append("\n资料原文：（暂无）")
        lines.append("\n小结：（暂无小结）")
        lines.append("\n困惑点：（暂无记录）")
        items = g.get("open_items") or []
        if not items:
            lines.append("\n未关闭错题：（无）")
        else:
            lines.append("\n未关闭错题：")
            for it in items:
                et = it.get("error_type") or "未分类"
                lines.append(
                    f"- {it.get('question_text', '')}（错因：{et}，已复习 {it.get('review_count', 0)} 次）"
                )
    return "\n".join(lines) + "\n"


async def build_cheatsheet(
    db: AsyncSession,
    student_id: uuid.UUID,
) -> dict:
    """每学生一份 Markdown 小抄：按 KC 分组，内容只取 KU 描述与错题行。"""
    from services.models import KnowledgeUnit

    rows = (
        await db.execute(
            select(WrongQuestion).where(
                WrongQuestion.student_id == student_id,
                WrongQuestion.graduated_at.is_(None),
                WrongQuestion.question_text.isnot(None),
                WrongQuestion.question_text != "",
            )
        )
    ).scalars().all()
    grouped: dict[str, list] = {}
    for r in rows:
        grouped.setdefault(_first_kc(r) or "", []).append(r)
    groups: list[dict] = []
    for kc, rs in sorted(grouped.items()):
        ku_name = None
        ku_desc = None
        if kc:
            ku = (await db.execute(select(KnowledgeUnit).where(KnowledgeUnit.id == kc))).scalar_one_or_none()
            if ku is not None:
                ku_name = ku.name
                ku_desc = ku.description
        groups.append(
            {
                "kc": kc or None,
                "ku_name": ku_name,
                "ku_description": ku_desc,
                "open_items": [
                    {
                        "question_text": r.question_text,
                        "error_type": (
                            r.error_type.value
                            if getattr(r.error_type, "value", None) is not None
                            else (str(r.error_type) if r.error_type is not None else None)
                        ),
                        "review_count": int(r.review_count or 0),
                    }
                    for r in rs
                ],
            }
        )
    return {
        "student_id": str(student_id),
        "open_count": len(rows),
        "groups": groups,
        "markdown": render_cheatsheet(groups),
    }
