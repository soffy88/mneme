"""
错题批改与入库 oskill
====================
oskill/paper_grading.py

职责：
1. 组合 grade_question 与 profiler_analyze。
2. 将错题持久化到数据库。
3. verify_steps_chain：OCR 出的学生解题步骤链逐步确定性校验（T.6），
   定位首个错误步骤——纯 sympy(oprim.verify_step)，禁止 LLM 判步（红线）。

Sibling oskill 互调（受限互调，深度≤2，被调 stateless）：
- oskill.solve_and_visualize — 题面可确定性求解时，以内核 solve_answer
  为权威标准答案（确定性优先红线），OCR 出的 correct_answer 不作数。
"""

from __future__ import annotations
import asyncio
import re
import uuid
from typing import Any, List, Optional
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import insert

from oprim.answer_judge import judge_answer
from oprim.llm_oprims import (
    grade_question,
    profiler_analyze,
    GradeResult,
    ProfilerResult,
)
from oprim.verify_step import StepVerifyInput, verify_step
from oskill.solve_and_visualize import SolveAndVisualizeInput, solve_and_visualize
from services.models import WrongQuestion, ErrorType
from data.guangdong_math_kc import KC_LIST


# ── T.6 学生解题步骤链确定性校验 ────────────────────────────────────────────

# 上标数字 → **n（x² → x**2），与 OCR 常见输出对齐
_SUPERS = {
    "⁰": "0",
    "¹": "1",
    "²": "2",
    "³": "3",
    "⁴": "4",
    "⁵": "5",
    "⁶": "6",
    "⁷": "7",
    "⁸": "8",
    "⁹": "9",
}
_SUPER_RE = re.compile("[" + "".join(_SUPERS) + "]+")


def _normalize_math(s: str) -> str:
    """步骤文本归一为 sympy 可解析：× ÷ · → * /，^ → **，上标 → **n，去逗号。"""
    s = _SUPER_RE.sub(lambda m: "**" + "".join(_SUPERS[c] for c in m.group()), s)
    return (
        s.replace("×", "*")
        .replace("·", "*")
        .replace("÷", "/")
        .replace("^", "**")
        .replace(",", "")
        .replace("，", "")
        .strip()
    )


def _parse_step_equation(step: str) -> Optional[tuple[Any, Any]]:
    """把单个步骤解析为 (lhs, rhs) sympy 表达式；非"恰一个等号"或解析失败 → None。"""
    if step.count("=") != 1:
        return None
    lhs_s, rhs_s = (x.strip() for x in step.split("="))
    if not lhs_s or not rhs_s:
        return None
    try:
        from sympy.parsing.sympy_parser import (
            parse_expr,
            standard_transformations,
            implicit_multiplication_application,
        )

        trans = standard_transformations + (implicit_multiplication_application,)
        return (
            parse_expr(_normalize_math(lhs_s), transformations=trans),
            parse_expr(_normalize_math(rhs_s), transformations=trans),
        )
    except Exception:
        return None


def _verify_equal(lhs_s: str, rhs_s: str) -> Optional[bool]:
    """用 oprim.verify_step 判定 lhs == rhs 是否恒成立；parse 失败 → None。"""
    result = verify_step(
        StepVerifyInput(
            step_number=1,
            before_lhs=lhs_s,
            before_rhs=rhs_s,
            after_lhs="0",
            after_rhs="0",  # 检验 before_lhs == before_rhs 是否成立
        )
    )
    if result.error_type == "parse_error":
        return None
    return result.is_correct


def verify_steps_chain(steps: List[str]) -> dict:
    """学生解题步骤链逐步确定性校验（T.6，纯 sympy，禁止 LLM 判步——红线）。

    Internal oprim composition:
    - oprim.verify_step（唯一校验内核，算术等式与代回检验都走它）

    对每个步骤给出 verdict ∈ {ok, wrong, unknown}，并定位首个 wrong 步骤。
    确定性能力边界（宁可 unknown，不误伤正确步骤）：
    1. 纯算术等式（如 "3+1=4"）→ verify_step 判两侧相等 → ok/wrong；
    2. 变量赋值步（"x = 3"）→ 数值代回**前序同一单变量**方程检验
       （思路同 services/socratic_service._verify_assignments 的消息级拦截，
       输入域不同：这里是 OCR 步骤列表）——任一前序方程不满足 → wrong，
       至少校验了一条且全部满足 → ok，无可校验前序 → unknown；
    3. 其余（含变量的一般方程变形，如 2x=6 → x=3 的中间恒等变形、多变量、
       无法解析、非单等号步）→ unknown：方程变形的解集等价无法用表达式
       恒等判定，不冒险判错。

    Parameters
    ----------
    steps : List[str]
        OCR 提取的学生手写步骤文本（按书写顺序）。

    Returns
    -------
    dict
        {"step_verdicts": [{"step_text": str, "verdict": "ok"|"wrong"|"unknown"}, ...],
         "first_wrong_step": int | None}   # 0-based 首个 wrong 的下标
    """
    parsed = [_parse_step_equation(s) for s in steps]
    verdicts: List[str] = []

    for i, step in enumerate(steps):
        eq = parsed[i]
        if eq is None:
            verdicts.append("unknown")
            continue
        lhs, rhs = eq

        # 类别 1：纯算术等式（两侧均无自由变量）
        if not lhs.free_symbols and not rhs.free_symbols:
            ok = _verify_equal(str(lhs), str(rhs))
            verdicts.append("unknown" if ok is None else ("ok" if ok else "wrong"))
            continue

        # 类别 2：变量赋值步（var = number 或 number = var）
        var = val = None
        if getattr(lhs, "is_Symbol", False) and getattr(rhs, "is_number", False):
            var, val = lhs, rhs
        elif getattr(rhs, "is_Symbol", False) and getattr(lhs, "is_number", False):
            var, val = rhs, lhs
        if var is not None:
            checked = 0
            failed = False
            for j in range(i):
                prev = parsed[j]
                if prev is None:
                    continue
                pl, pr = prev
                syms = pl.free_symbols | pr.free_symbols
                if syms != {var}:
                    continue  # 仅校验同一单变量的前序方程
                try:
                    ok = _verify_equal(str(pl.subs(var, val)), str(pr.subs(var, val)))
                except Exception:
                    continue
                if ok is None:
                    continue
                checked += 1
                if not ok:
                    failed = True
                    break
            if failed:
                verdicts.append("wrong")
            elif checked > 0:
                verdicts.append("ok")
            else:
                verdicts.append("unknown")
            continue

        # 类别 3：一般含变量变形 → unknown
        verdicts.append("unknown")

    first_wrong = next((i for i, v in enumerate(verdicts) if v == "wrong"), None)
    return {
        "step_verdicts": [
            {"step_text": s, "verdict": v} for s, v in zip(steps, verdicts)
        ],
        "first_wrong_step": first_wrong,
    }


def _step_evidence_from_chain(chain: dict) -> Optional[str]:
    """步骤链 → careless/dontknow 证据（T.6，供 cognitive_update 平局判定）。

    规则（依据：末答错 + 过程全对/仅末步错 → 粗心迹象；早期步骤即错 → 不会迹象）：
    - 无确定性错步且至少一步 ok → "careless"（步骤看起来对，答案却错）；
    - 首错步 == 最末一步 → "careless"；
    - 首错步落在前 1/3（0-based 下标 < n/3）→ "dontknow"；
    - 其余（全 unknown、中段出错等）→ None（不给证据）。
    该证据只在 BKT 两假设权重近平局时打破平局（见 oskill.cognitive_state），
    不改 classify 红线公式。
    """
    verdicts = [v["verdict"] for v in chain["step_verdicts"]]
    n = len(verdicts)
    if n == 0:
        return None
    fw = chain["first_wrong_step"]
    if fw is None:
        return "careless" if any(v == "ok" for v in verdicts) else None
    if fw == n - 1:
        return "careless"
    if fw < n / 3.0:
        return "dontknow"
    return None


async def process_single_question(
    *,
    session: AsyncSession,
    student_id: uuid.UUID,
    paper_id: Optional[uuid.UUID],
    question_text: str,
    student_answer: str,
    correct_answer: str,
    subject: str = "math",
    student_steps: Optional[List[str]] = None,
) -> dict:
    """
    处理单题批改：内核复核标准答案 -> 判定对错 -> (若错) 认知分析 -> 入库。

    Internal oprim composition:
    - oprim.judge_answer
    - oprim.grade_question
    - oprim.profiler_analyze
    - oprim.verify_step（经 verify_steps_chain，答错且有步骤时定位首个错步）

    Sibling oskill calls (受限互调，深度≤2，被调 stateless):
    - oskill.solve_and_visualize（题面可解时以内核值为权威标准答案）

    student_steps：OCR 提取的学生手写解题步骤（T.6）。None/[]（默认）行为与
    无步骤基线一致；答错且有步骤时结果带 step_verdicts/first_wrong_step/
    step_evidence，并把步骤分析存入 wrong_questions.step_analysis。
    """

    # 0. 内核复核（确定性优先红线）：有 solve_* 覆盖的题型，数值结论必来自内核。
    #    题面能被 solve_and_visualize 确定性求解（solvable=True）时，以内核
    #    solve_answer 为权威 correct_answer 参与判分——OCR 出的标准答案可能识别
    #    错或本身抄错，与内核不一致时以内核为准；不可解题型行为不变（answer_source=ocr）。
    answer_source = "ocr"
    sv_res = await asyncio.to_thread(
        solve_and_visualize,
        SolveAndVisualizeInput(expression=question_text, generate_svg=False),
    )
    if sv_res.solvable and sv_res.solve_answer:
        correct_answer = sv_res.solve_answer
        answer_source = "kernel"

    # 1. 批改（确定性优先红线）：标准答案（内核值或试卷自带）是真值，
    #    故先用确定性比对 judge_answer（选择题/可规范化短答），只有它 unsure
    #    时才退回 LLM 等价判定——杜绝"可确定性判定的题由 LLM 误判"。
    verdict = judge_answer(student_answer, correct_answer)["verdict"]
    if verdict == "correct":
        return {
            "status": "correct",
            "grade_method": "deterministic",
            "answer_source": answer_source,
        }
    if verdict == "wrong":
        grade_method = "deterministic"
    else:  # unsure → 自由作答/长答，退回 LLM 等价判定
        grade_res: GradeResult = await grade_question(
            question_text=question_text,
            student_answer=student_answer,
            correct_answer=correct_answer,
        )
        if grade_res.is_correct:
            return {
                "status": "correct",
                "grade_method": grade_res.method,
                "answer_source": answer_source,
            }
        grade_method = grade_res.method

    # 1.5 步骤链确定性校验（T.6）：答错且 OCR 出了步骤 → 逐步过 verify_step
    #     定位首个错步（纯 sympy，红线：错误中间步由 verify_step 拦截，不靠 LLM）。
    step_analysis: Optional[dict] = None
    step_evidence: Optional[str] = None
    if student_steps:
        chain = await asyncio.to_thread(verify_steps_chain, list(student_steps))
        step_evidence = _step_evidence_from_chain(chain)
        step_analysis = {
            "student_steps": list(student_steps),
            "step_verdicts": chain["step_verdicts"],
            "first_wrong_step": chain["first_wrong_step"],
        }

    # 2. 错题分析
    # 获取候选 KC 列表供 LLM 参考 (全量 KC ID)
    kc_candidates = [k["kc_id"] for k in KC_LIST]

    profiler_res: ProfilerResult = await profiler_analyze(
        question_text=question_text,
        student_answer=student_answer,
        correct_answer=correct_answer,
        kc_candidates=kc_candidates,
    )

    # 3. 错题入库
    wq_id = uuid.uuid4()
    ins_stmt = insert(WrongQuestion).values(
        id=wq_id,
        paper_id=paper_id,
        student_id=student_id,
        subject=subject,
        question_text=question_text,
        student_answer=student_answer,
        correct_answer=correct_answer,
        knowledge_points={"ids": profiler_res.knowledge_points},
        error_type=ErrorType(profiler_res.error_type),
        profiler_analysis=profiler_res.model_dump(),
        step_analysis=step_analysis,
        created_at=datetime.now(timezone.utc),
    )
    await session.execute(ins_stmt)
    # 调用方负责 commit 或 session 管理

    result = {
        "status": "wrong",
        "wq_id": str(wq_id),
        "grade_method": grade_method,
        "answer_source": answer_source,
        "error_type": profiler_res.error_type,
        "knowledge_points": profiler_res.knowledge_points,
        "parent_note": profiler_res.parent_note,
    }
    if step_analysis is not None:
        result["step_verdicts"] = step_analysis["step_verdicts"]
        result["first_wrong_step"] = step_analysis["first_wrong_step"]
        result["step_evidence"] = step_evidence
    return result


__version__ = "0.2.0"
__manifest__ = {
    "version": __version__,
    "updated_at": "2026-07-02",
    "elements": [
        {
            "name": "process_single_question",
            "layer": "oskill",
            "summary": "批改、分析并存入错题库（含步骤链定位首个错步）",
        },
        {
            "name": "verify_steps_chain",
            "layer": "oskill",
            "summary": "学生步骤链逐步确定性校验（verify_step，无 LLM）",
        },
    ],
}
