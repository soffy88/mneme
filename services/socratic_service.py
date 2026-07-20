"""F.1 — Socratic session service (assembly only).

Layer-4 rule: assembly + DB only; business logic lives in omodul/oskill.
"""

from __future__ import annotations

import json
import re as _re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncGenerator, Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from omodul.socratic_session_workflow import (
    SocraticConfig,
    SocraticInput,
    socratic_session_workflow,
)
from services.learner_model import YELLOW
from services.models import (
    KCMastery,
    SocraticMode,
    SocraticOutcome,
    SocraticSession,
    WrongQuestion,
)
from services.anon import anon_ref

from oskill.metacog_scaffold import metacog_scaffold, MetacogScaffoldInput
from obase.provider_registry import ProviderRegistry
from obase.sympy_runtime import SymPyRuntime

_runtime = SymPyRuntime()


async def start_session(
    db: AsyncSession, question_id: uuid.UUID, student_id: uuid.UUID
) -> dict:
    """Initialize a Socratic session; call omodul for first_question."""
    wq = (
        await db.execute(select(WrongQuestion).where(WrongQuestion.id == question_id))
    ).scalar_one_or_none()
    if not wq:
        return {"error": "question not found"}

    kc_id = ""
    textbook_id = ""
    mastery_row = None
    if wq.knowledge_points:
        kc_ids = (
            list(wq.knowledge_points.keys())
            if isinstance(wq.knowledge_points, dict)
            else []
        )
        if kc_ids:
            kc_id = kc_ids[0]

            from services.models import KnowledgeUnit

            ku = (
                await db.execute(select(KnowledgeUnit).where(KnowledgeUnit.id == kc_id))
            ).scalar_one_or_none()
            if ku and getattr(ku, "textbook_id", None):
                textbook_id = str(ku.textbook_id)

            mastery_row = (
                await db.execute(
                    select(KCMastery).where(
                        KCMastery.student_id == student_id,
                        KCMastery.knowledge_point == kc_id,
                    )
                )
            ).scalar_one_or_none()

    p_mastery = mastery_row.p_mastery if mastery_row else 0.5
    mode = "deep" if (p_mastery or 0) < YELLOW else "mixed"

    session_id = uuid.uuid4()
    session = SocraticSession(
        id=session_id,
        student_id=student_id,
        question_id=question_id,
        mode=SocraticMode.deep if mode == "deep" else SocraticMode.mixed,
        messages=[],
    )
    db.add(session)
    await db.flush()

    # 首问扣题（确定性优先）：基于真实题面构造锚定问题，不让 LLM 漂成通用问句
    q_snippet = " ".join((wq.question_text or "").split())
    if len(q_snippet) > 60:
        q_snippet = q_snippet[:60] + "…"
    anchored_q = (
        f"我们来看这道题：「{q_snippet}」。先别急着算——你觉得这道题在考查什么？打算从哪一步入手？"
        if q_snippet
        else "请仔细审题，你认为这道题考察的是什么知识点？"
    )
    # T.6：拍卷步骤批改定位过首个错步（verify_step 确定性）→ 首问附带位置提示。
    # 只指出"第几步"，不含正确答案/步骤内容（苏格拉底红线）。
    if isinstance(wq.step_analysis, dict):
        fw = wq.step_analysis.get("first_wrong_step")
        if isinstance(fw, int) and fw >= 0:
            anchored_q += f"（提示：你当时的解题过程从第 {fw + 1} 步开始出了问题，可以先回想一下那一步。）"
    # 强制元认知支架 (Metacog Scaffold)
    metacog_options = []
    first_q = anchored_q
    if mode != "sprint":
        try:
            caller = (
                ProviderRegistry.get().llm() if ProviderRegistry._instance else None
            )
        except Exception:
            caller = None
        try:
            meta_res = await metacog_scaffold(
                MetacogScaffoldInput(
                    question=wq.question_text or "未知题目",
                    student_id=str(student_id),
                    input_content="刚开始看题",
                ),
                caller=caller,
            )
            metacog_data = meta_res.self_eval
            # 保留确定性锚定首问；仅采用 metacog 的识别脚手架选项
            metacog_options = metacog_data.get("options", [])

            # Record it as the first system/assistant message in SocraticSession
            session.messages = [
                {"role": "assistant", "content": first_q, "options": metacog_options}
            ]  # type: ignore[assignment]  # JSONB column 实际存放消息列表
            await db.flush()
        except Exception:
            pass  # fallback to default if metacog fails

    from oprim.learner_profile_summary import get_latest_learner_profile

    learner_profile = await get_latest_learner_profile(db, student_id)

    result = await socratic_session_workflow(
        config=SocraticConfig(mode=mode, max_turns=20),
        input_data=SocraticInput(
            question_text=wq.question_text or "",
            correct_answer=wq.correct_answer or "",
            kc_id=kc_id,
            profiler_result={},
            student_messages=[],
            user_id=anon_ref(student_id),
            learner_profile=learner_profile,
            textbook_id=textbook_id,
        ),
        output_dir=Path(f"/tmp/mneme/socratic/{session_id}"),
        on_step=None,
    )

    if mode == "sprint":
        first_q = result.get("first_question", first_q)

    return {
        "session_id": str(session_id),
        "mode": mode,
        "first_question": first_q,
        "metacog_options": metacog_options,
    }


async def socratic_message_stream(
    db: AsyncSession,
    session_id: uuid.UUID,
    student_message: str,
) -> AsyncGenerator[str, None]:
    """Yield SSE events for a Socratic turn via omodul (red line: no answer leakage)."""
    session = (
        await db.execute(
            select(SocraticSession).where(SocraticSession.id == session_id)
        )
    ).scalar_one_or_none()
    if not session:
        yield f"data: {json.dumps({'error': 'session not found'})}\n\n"
        return

    wq = (
        await db.execute(
            select(WrongQuestion).where(WrongQuestion.id == session.question_id)
        )
    ).scalar_one_or_none()
    if not wq:
        yield f"data: {json.dumps({'error': 'question not found'})}\n\n"
        return

    kc_id = ""
    if wq.knowledge_points:
        kcs = (
            list(wq.knowledge_points.keys())
            if isinstance(wq.knowledge_points, dict)
            else []
        )
        if kcs:
            kc_id = kcs[0]

    textbook_id = ""
    if kc_id:
        from services.models import KnowledgeUnit

        ku = (
            await db.execute(select(KnowledgeUnit).where(KnowledgeUnit.id == kc_id))
        ).scalar_one_or_none()
        if ku and getattr(ku, "textbook_id", None):
            textbook_id = str(ku.textbook_id)

    messages = list(session.messages or [])

    # H.3: verify_step deterministic intercept before Socratic reply
    step_error = _try_verify_step(student_message)

    sse_chunks: list[str] = []

    if step_error:
        reply = "这一步有问题，再想想。" + step_error
        sse_chunks = reply.split()
    else:
        # item 12：传真实历史对话（含 assistant 真实回复）+ 仅本轮新消息，
        # 让模型看到真实历史且每轮 O(1)（不再重算所有历史 user 轮）。
        history = [
            {"role": m.get("role", "user"), "content": str(m.get("content", ""))}
            for m in messages
        ]

        from oprim.learner_profile_summary import get_latest_learner_profile

        learner_profile = await get_latest_learner_profile(db, session.student_id)

        result = await socratic_session_workflow(
            config=SocraticConfig(
                mode=session.mode.value if session.mode else "mixed",
                max_turns=20,
            ),
            input_data=SocraticInput(
                question_text=wq.question_text or "",
                correct_answer=wq.correct_answer or "",
                kc_id=kc_id,
                profiler_result={},
                student_messages=[student_message],
                conversation_history=history,
                user_id=anon_ref(session.student_id),
                learner_profile=learner_profile,
                textbook_id=textbook_id,
            ),
            output_dir=Path(f"/tmp/mneme/socratic/{session_id}"),
            on_step=None,
        )
        reply = result.get("first_question", "继续思考，下一步怎么做？")
        sse_chunks = reply.split()

    messages.append({"role": "user", "content": student_message})
    messages.append({"role": "assistant", "content": reply})
    await db.execute(
        update(SocraticSession)
        .where(SocraticSession.id == session_id)
        .values(messages=messages)
    )
    await db.flush()

    turn = len([m for m in messages if m.get("role") == "assistant"])
    for chunk in sse_chunks:
        yield f"data: {json.dumps({'delta': chunk + ' '})}\n\n"
    yield f"data: {json.dumps({'done': True, 'turn': turn})}\n\n"


# 纯算术片段：仅数字/运算符/括号/小数/常见 unicode 运算符（无变量/文字）
_ARITH_CHARS = r"\d\s+\-*/^().,×÷·"
_ARITH_LEFT = _re.compile(rf"[{_ARITH_CHARS}]+$")
_ARITH_RIGHT = _re.compile(rf"^[{_ARITH_CHARS}]+")

# 上标数字 → **n（x² → x**2）
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
_SUPER_RE = _re.compile("[" + "".join(_SUPERS) + "]+")
# 等式分隔：标点 + 中文推导连接词
_EQ_SPLIT = _re.compile(r"[,;，；]|所以|因此|于是|=>|⟹|→|得到|得|则|故")
# 隐式乘法（"2x"/"2 pi" -> "2*x"/"2*pi"）：数字与紧随其后的字母之间插入 *，
# 中间可以有空白也可以没有，绝不会误伤函数调用。S0-W5 改走沙箱化的
# obase.sympy_runtime（纯 Python ast.parse，不支持 sympy 自己 parse_expr() 的
# implicit_multiplication_application 变换，那个变换在 token 流层面同时处理
# 无空白/有空白两种形式）后，需要在归一化阶段自己补上——最初只处理了无空白
# 形式（本函数文档字符串举的「2x=6 ⟹ x=3」这个例子依赖它），全量回归测试
# （math_grade 的 test_pi_and_sqrt）抓到"2 pi"这种带空格形式被漏解析。
_IMPLICIT_MULT_RE = _re.compile(r"(?<=[0-9])\s*(?=[A-Za-z])")


def _normalize_arith(s: str) -> str:
    """归一为 sympy 可解析：× ÷ · → * /，^ → **，上标 → **n，去千分位逗号/空格，
    数字紧跟字母处补隐式乘号（2x -> 2*x）。"""
    s = _SUPER_RE.sub(lambda m: "**" + "".join(_SUPERS[c] for c in m.group()), s)
    s = (
        s.replace("×", "*")
        .replace("·", "*")
        .replace("÷", "/")
        .replace("^", "**")
        .replace(",", "")
        .replace("，", "")
        .strip()
    )
    return _IMPLICIT_MULT_RE.sub("*", s)


def _verify_assignments(message: str) -> Optional[str]:
    """确定性中间步拦截（含变量，红线扩展 item 3）。

    在一条消息内识别"变量 = 具体数值"的断言，把该数值代回**同一变量的**前序方程，
    用 sympy 检验是否成立——deterministic、不靠 LLM。
    例：「x² = 4, 所以 x = 3」→ 代 3 回 x²=4 得 9≠4 → 拦截；x=2 / x=-2 则成立不拦。
    正确的缩放步（2x=6 ⟹ x=3）也成立不拦（避免误伤）。
    多变量前序方程、无法解析、单方程消息一律不拦（宁可不拦，不误伤）。
    返回提示（不含正确答案）或 None。
    """
    parts = [p.strip() for p in _EQ_SPLIT.split(message)]
    eqs: list[tuple[str, str]] = []
    for p in parts:
        if p.count("=") != 1:
            continue
        lhs, rhs = (x.strip() for x in p.split("="))
        if lhs and rhs:
            eqs.append((lhs, rhs))
    if len(eqs) < 2:
        return None
    import sympy as sp

    # S0-W5：message 是真实学生聊天消息，外部输入。之前直接用
    # sympy.parsing.sympy_parser.parse_expr()（同 sp.sympify() 一类风险，
    # 零 AST 白名单/timeout/内存上限），这里改走沙箱化的
    # obase.sympy_runtime.evaluate_auto()（自动声明表达式里出现的单字母
    # 自由变量为 Symbol，隐式乘法在 _normalize_arith 里已经补好）。
    def _p(s: str):
        result = _runtime.evaluate_auto(_normalize_arith(s), simplify_result=False)
        if not result.success or result.value is None:
            raise ValueError(result.error or f"Failed to parse: {s!r}")
        return result.value

    parsed: list[Optional[tuple]] = []
    for lhs, rhs in eqs:
        try:
            parsed.append((_p(lhs), _p(rhs)))
        except Exception:
            parsed.append(None)
    for j in range(1, len(parsed)):
        cur = parsed[j]
        if not cur:
            continue
        L, R = cur
        if getattr(L, "is_Symbol", False) and getattr(R, "is_number", False):
            var, val = L, R
        elif getattr(R, "is_Symbol", False) and getattr(L, "is_number", False):
            var, val = R, L
        else:
            continue
        for i in range(j):
            prev = parsed[i]
            if not prev:
                continue
            PL, PR = prev
            syms = PL.free_symbols | PR.free_symbols
            if var not in syms or (syms - {var}):
                continue  # 仅校验同一单变量的前序方程
            try:
                if sp.simplify((PL - PR).subs(var, val)) != 0:
                    return "（把你算出的值代回原式好像不成立，自己代入检验一下这步。）"
            except Exception:
                continue
    return None


def _try_verify_step(message: str) -> Optional[str]:
    """确定性步骤拦截（H.3，红线：确定性、不泄露答案）。

    两道防线（确定性、不泄露答案）：
    1) 含变量代入校验（_verify_assignments）：消息内"变量=数值"代回同变量前序方程。
    2) 纯算术等式校验（如 "2+3=6"）——用 sympy(verify_step) 判定。
    无法脱离上下文判真伪的孤立含变量等式仍**不拦**，避免误伤正确步骤。
    返回错误提示（不含正确数值）或 None。
    """
    if "=" not in message:
        return None
    assign_err = _verify_assignments(message)
    if assign_err:
        return assign_err
    for m in _re.finditer("=", message):
        i = m.start()
        left = _ARITH_LEFT.search(message[:i])
        right = _ARITH_RIGHT.search(message[i + 1 :])
        if not left or not right:
            continue
        a, b = left.group().strip(), right.group().strip()
        # 两侧都必须含数字，且都是纯算术（否则可能含变量/文字 → 跳过）
        if not (_re.search(r"\d", a) and _re.search(r"\d", b)):
            continue
        try:
            from oprim.verify_step import StepVerifyInput, verify_step

            result = verify_step(
                StepVerifyInput(
                    step_number=1,
                    before_lhs=_normalize_arith(a),
                    before_rhs=_normalize_arith(b),
                    after_lhs="0",
                    after_rhs="0",  # 检验 a == b 是否成立
                )
            )
            if result.error_type == "parse_error":
                continue
            if not result.is_correct:
                return "（这一步的算式好像对不上，自己再算一遍这步看看。）"
        except Exception:
            continue
    return None


async def escape_session(db: AsyncSession, session_id: uuid.UUID) -> dict:
    """Return answer outline; never reveal full correct_answer (red line)."""
    session = (
        await db.execute(
            select(SocraticSession).where(SocraticSession.id == session_id)
        )
    ).scalar_one_or_none()
    if not session:
        return {"error": "session not found"}
    await db.execute(
        update(SocraticSession)
        .where(SocraticSession.id == session_id)
        .values(used_escape_hatch=True)
    )
    return {
        "outline": ["分析题意", "列出公式", "代入计算", "验证答案"],
        "note": "思路提示，非标准答案",
    }


async def end_session(
    db: AsyncSession, session_id: uuid.UUID, outcome: str = "partial"
) -> dict:
    """End session, map outcome to FSRS rating.

    红线（item 9，数据完整性）：outcome 由客户端给只是**提示**，不可信。
    服务层用确定性 judge_answer 核对学生对话里是否真的说出正确答案，
    再决定喂给 BKT 的信号——未核实的 success 一律降级为 partial（不更新），
    杜绝前端伪报 success 污染掌握度。
    """
    outcome_map = {
        "success": SocraticOutcome.success,
        "partial": SocraticOutcome.partial,
        "failed": SocraticOutcome.failed,
        "abandoned": SocraticOutcome.abandoned,
    }
    now = datetime.now(timezone.utc)
    session = (
        await db.execute(
            select(SocraticSession).where(SocraticSession.id == session_id)
        )
    ).scalar_one_or_none()
    if not session:
        return {"error": "session not found"}

    wq = (
        await db.execute(
            select(WrongQuestion).where(WrongQuestion.id == session.question_id)
        )
    ).scalar_one_or_none()

    # 确定性核对：仅当存在标准答案(answer key)时才核实——有真值才谈得上防伪报。
    answer_key = (wq.correct_answer or "").strip() if wq else ""
    has_answer_key = bool(answer_key)
    verified_success = False
    if has_answer_key:
        from oprim.answer_judge import judge_answer

        for m in session.messages or []:
            if m.get("role") != "user":
                continue
            content = str(m.get("content", ""))
            # 候选：整句 + "=" 之后的值（学生常写 "x = 2"，答案存为 "2"）
            cands = [content]
            if "=" in content:
                cands.append(content.rsplit("=", 1)[-1])
            if any(
                judge_answer(c, answer_key).get("verdict") == "correct" for c in cands
            ):
                verified_success = True
                break

    # 由"客户端提示 + 服务端核实"推导可信 outcome：
    #   有标准答案时强制核实，未核实的 success 降级为 partial（不更新、不污染）；
    #   无标准答案无法核实时信任客户端提示（避免误杀正当信号）。
    if verified_success:
        effective = "success"
    elif has_answer_key and outcome == "success":
        effective = "partial"
    else:
        effective = outcome

    soc_outcome = outcome_map.get(effective, SocraticOutcome.partial)
    duration = (
        int((now - session.created_at).total_seconds()) if session.created_at else 0
    )
    await db.execute(
        update(SocraticSession)
        .where(SocraticSession.id == session_id)
        .values(outcome=soc_outcome, duration_seconds=duration)
    )
    await db.flush()

    # 苏格拉底结果驱动认知更新（Master：outcome 映射 FSRS rating）
    #   success → 答对；failed → 答错(struggled)；partial/abandoned → 不更新
    kc_updated = False
    if effective in ("success", "failed") and wq and wq.knowledge_points:
        kc_id = next(iter(wq.knowledge_points.keys()))
        from services.cognitive_service import process_interaction

        assert session.student_id is not None
        await process_interaction(
            db,
            student_id=session.student_id,
            kc_id=kc_id,
            is_correct=(effective == "success"),
            question_type="solve",
            question_id=session.question_id,
            source="socratic",
            struggled=True,  # 苏格拉底本身即"吃力"过程（努力收益 M-F）
        )
        kc_updated = True

    return {
        "session_id": str(session_id),
        "outcome": effective,
        "client_outcome": outcome,
        "verified_success": verified_success,
        "duration_seconds": duration,
        "kc_updated": kc_updated,
    }
