"""mcp_router — Phase1 门控内核的 MCP 工具面（架构 A：挂进 mneme app）。

agent 经 HTTP 调这些工具触达掌握度，**自身零 DB 连接**。工具面（Layer4）可调
纯库 mneme-core（is_mastered/next_objective）+ gate_store + 既有 process_interaction。

红线：期望答案（expected）只存 gate.pending_question，**任何工具响应都不外传**。

鉴权（W2b 起）：/mcp 已随 studio 公网暴露到 sxueji.com/mcp，**W1 的"内部可信、靠网络
隔离免鉴权"前提已废**。所有 HTTP 端点必须携带 JWT（与 mneme-web 同一套 `mneme_token`，
studio 同源复用），student_id 服务端按越权规则校验（读=本人或绑定家长；写认知数据=仅本人）
——不再信任 body 里的 student_id。tool_* 纯逻辑函数签名不变（仍可脱 HTTP 直测）。

- NextObjective 暂由请求携带 kc_ids（学习路径）；路径持久化留后续。
"""

from __future__ import annotations

import re
import time
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from mneme_core.oprim.grade import answer_match
from mneme_core.oprim.mastery_gate import (
    N_MIN,
    QUALITATIVE_TYPES,
    Z,
    is_mastered,
    next_objective,
)
from mneme_core.oprim.quiz_selection import DifficultyCurve
from mneme_core.oprim.spacing import due_reviews
from mneme_core.oskill.quiz_generator import quiz_generator
from mneme_core.service.verdict_guard import GuardRejection, enforce

from obase.db import get_db
from services import gate_store, memory, persona_store, rag_client
from services.auth_deps import (
    _ensure_student_access,
    _ensure_student_self,
    get_current_user,
)
from services.math_grade import grade_math
from services.models import KnowledgeCluster, KnowledgeUnit, User, WrongQuestion
from services.progress_assembler import build_learning_progress

router = APIRouter(prefix="/mcp", tags=["mcp"])


# ── 工具逻辑（可脱离 HTTP 直测）─────────────────────────────────────────────

# 内容就绪的默认教材（MVP 只有广东高中数学 renjiao-math-g10-a 备好了题库/rubric）；
# 未来按学生 grade 映射教材，此处留扩展点。
DEFAULT_TEXTBOOK = "renjiao-math-g10-a"

# "有内容"KC：有非图形题库题（选择题选项可从 profiler 恢复）或有 rubric（定性）。
_CONTENT_KC_SQL = text(
    """
    SELECT DISTINCT jsonb_object_keys(knowledge_points) AS kc
    FROM wrong_questions
    WHERE needs_image = false AND question_text NOT LIKE '%<ImageHere>%'
    UNION
    SELECT kc_id FROM gate.rubric
    """
)


async def tool_get_path(
    db: AsyncSession, student_id: uuid.UUID, textbook_id: str = DEFAULT_TEXTBOOK
) -> dict:
    """按学生档案拉学习路径：该教材"有内容"的 KU、按**章节序**(cluster.display_order)排列。

    排序取 cluster.display_order（教材编排序：集合→逻辑→不等式→三角…，比纯前置拓扑更贴课程，
    因很多 KU 的真实前置在早年级、被剥离后拓扑会误判其"无前置"），同章内按难度升序。
    派生式（不落新表）：确定性派生→跨会话稳定=持久；学生位置由掌握度追踪
    （NextObjective 取路径中下一个未过门 KC）。教材现固定 DEFAULT_TEXTBOOK，按 grade 映射留
    扩展点。过滤同 RequestQuestion：只留自足可作答/可判分的 KC。
    """
    content = {r[0] for r in (await db.execute(_CONTENT_KC_SQL)).all() if r[0]}
    rows = (
        await db.execute(
            select(KnowledgeUnit.id)
            .join(KnowledgeCluster, KnowledgeUnit.cluster_id == KnowledgeCluster.id)
            .where(KnowledgeUnit.textbook_id == textbook_id)
            .order_by(
                KnowledgeCluster.display_order,
                KnowledgeUnit.difficulty,
                KnowledgeUnit.id,
            )
        )
    ).all()
    kc_ids = [r[0] for r in rows if r[0] in content]
    return {"textbook_id": textbook_id, "kc_ids": kc_ids}


async def tool_generate_quiz(
    db: AsyncSession,
    student_id: uuid.UUID,
    *,
    kc_ids: Optional[list[str]] = None,
    size: int = 10,
    difficulty_curve: DifficultyCurve = "ascending",
    exclude_mastered: bool = True,
) -> dict:
    """组卷（C2）：选 KC + 难度序列，**不选具体题、不判分**。

    候选池不传则用 GetPath 的默认路径 KC。选中的每个 KC 仍经既有 RequestQuestion
    （AA.7/AA.9/AA.10 过滤）逐题出题，SubmitAnswer + guard 判分回流
    process_interaction——组卷不新开第二条出题/判分路径，S1 判分 CI 门约束不变。
    """
    if kc_ids is None:
        path = await tool_get_path(db, student_id)
        kc_ids = path["kc_ids"]

    progress = await build_learning_progress(db, student_id, kc_ids)
    candidates = progress.modules[0].knowledge_points
    selected = quiz_generator(
        progress,
        candidates,
        size=size,
        difficulty_curve=difficulty_curve,
        exclude_mastered=exclude_mastered,
    )
    return {
        "kc_sequence": [kp.id for kp in selected],
        "size": len(selected),
    }


async def tool_next_objective(
    db: AsyncSession,
    student_id: uuid.UUID,
    kc_ids: list[str],
    now: Optional[float] = None,
) -> dict:
    """组装 progress → next_objective → 序列化（**绝不含 expected**）。"""
    # 自愈：清掉遗留的坏 pending（题干含 <ImageHere> 占位、无法作答，AA.7 前出的）。
    # 否则 build_learning_progress 会把它当 has_pending 返回、studio 照显、学生卡死。
    active = await gate_store.get_active_pending(db, student_id=student_id)
    if active is not None and "<ImageHere>" in (active["prompt"] or ""):
        await gate_store.clear_pending(
            db, student_id=student_id, question_id=active["question_id"]
        )
        await db.commit()
    prog = await build_learning_progress(db, student_id, kc_ids)
    step = next_objective(prog, now=now or time.time())

    resp: dict = {
        "action": step.action.value,
        "kc_id": step.kc_id,
        "kc_name": step.kc_name,
        "kc_type": step.kc_type.value if step.kc_type else None,
        "module_id": step.module_id,
        "has_pending": step.pending_question is not None,
    }
    if step.pending_question is not None:
        pq = step.pending_question
        # 红线：只回 question_id/prompt/qtype，绝不回 expected。
        resp["pending_question"] = {
            "question_id": pq.question_id,
            "prompt": pq.prompt,
            "qtype": pq.qtype,
        }
    if step.review_task is not None:
        resp["review_task"] = {
            "kc_id": step.review_task.knowledge_point_id,
            "due_at": step.review_task.due_at,
            "priority": step.review_task.priority,
        }
    return resp


async def tool_get_kc_info(db: AsyncSession, kc_id: str) -> dict:
    """KC 元数据 + rubric（供 agent 跑 qualitative_verifier）。无此 KC → {error}。"""
    row = (
        await db.execute(
            select(KnowledgeUnit.name, KnowledgeUnit.prerequisites).where(
                KnowledgeUnit.id == kc_id
            )
        )
    ).first()
    if row is None:
        return {"error": "kc not found", "kc_id": kc_id}

    gate_type = await gate_store.resolve_gate_type(db, kc_id)
    rubric = await gate_store.get_rubric(db, kc_id)  # None 则不可 assess（fail-safe）
    return {
        "kc_id": kc_id,
        "name": row.name,
        "gate_type": gate_type,
        "prerequisites": row.prerequisites or [],
        "rubric": rubric,
    }


async def tool_list_personas(db: AsyncSession) -> dict:
    """列出可选人格模板（不含 body，供 chat 前端选择器用）。"""
    return {"personas": await persona_store.list_personas(db)}


async def tool_get_persona(db: AsyncSession, slug: str) -> dict:
    """取单个人格模板 + 渲染好的 system prompt 块（供 chat/tutor loop 拼进上下文）。

    不存在 → 回落默认人格（DEFAULT_PERSONA_SLUG），不报错——人格缺失不该打断对话。
    """
    persona = await persona_store.get_persona(db, slug)
    if persona is None:
        persona = await persona_store.get_persona(
            db, persona_store.DEFAULT_PERSONA_SLUG
        )
    if persona is None:
        return {"error": "no persona templates available"}
    return {
        "slug": persona["slug"],
        "name": persona["name"],
        "prompt_block": persona_store.render_for_prompt(persona),
    }


async def tool_recall_memory(
    db: AsyncSession, student_id: uuid.UUID, topic: Optional[str] = None
) -> dict:
    """C5：召回呈现层记忆上下文（agent.semantic_memory），供 loop 拼进对话背景。

    红线：memory 是呈现层上下文，不进门控判据——本工具只读 agent.* schema，
    与 kc_mastery/gate.* 完全无关，返回值不影响任何过门判定。
    """
    return await memory.recall(db, student_id, topic=topic)


async def tool_remember_episode(
    db: AsyncSession,
    student_id: uuid.UUID,
    *,
    kind: str,
    content: dict,
    session_id: Optional[str] = None,
) -> dict:
    """C5：写一条 episodic 记忆（只增不改），供 loop 记录"这轮聊了什么"。"""
    return await memory.append_episode(
        db, student_id, kind=kind, content=content, session_id=session_id
    )


async def tool_search_knowledge_base(query: str, top_k: int = 5) -> dict:
    """C4：检索 Stratum 知识库素材，供 loop 拼进对话背景（呈现层，不进门控判据）。

    不需要 db——不碰 mneme 任何表，纯代理转发给 rag_client（Stratum 侧才有状态）。
    Stratum 不可用（无凭据/网络失败）→ results 为空列表，不报错，不阻断对话。
    """
    return {"results": await rag_client.search(query, top_k=top_k)}


async def tool_check_mastery(
    db: AsyncSession, student_id: uuid.UUID, kc_id: str
) -> dict:
    """单 KC 掌握度快照：p_learned / 下界 / n_obs / is_mastered / fsrs_due。"""
    prog = await build_learning_progress(db, student_id, [kc_id])
    kp = prog.modules[0].knowledge_points[0]
    post = prog.bkt.get(kc_id)
    fsrs = prog.fsrs.get(kc_id)

    lower_bound = 0.0
    if post is not None:
        lower_bound = max(0.0, post.p_learned - Z * post.sigma)

    # gate_type 用 D2.2 词汇（qualitative/quantitative），与 GetKCInfo 一致；
    # 不外泄 mneme-core 内部枚举名（procedure/concept…）。
    gate_type = (
        gate_store.QUALITATIVE
        if kp.type in QUALITATIVE_TYPES
        else gate_store.QUANTITATIVE
    )

    return {
        "kc_id": kc_id,
        "gate_type": gate_type,
        "p_learned": post.p_learned if post else 0.0,
        "p_learned_lower_bound": lower_bound,
        "n_obs": post.n_obs if post else 0,
        "confident": (post.n_obs >= N_MIN) if post else False,
        "is_mastered": is_mastered(prog, kp),
        "fsrs_due": fsrs.due_at if fsrs else None,
    }


async def tool_get_review_queue(
    db: AsyncSession,
    student_id: uuid.UUID,
    kc_ids: list[str],
    now: Optional[float] = None,
) -> dict:
    """到期复习队列：assembler 组装 review_queue → `due_reviews` 过滤到期 + 排序。

    排序 = (priority, due_at) 升序：error-linked(priority=1) 先出（V11/§4）。
    复习本已可经 NextObjective 优先级 2 驱动；本工具是便捷只读快照（第 7 工具）。
    """
    prog = await build_learning_progress(db, student_id, kc_ids)
    due = due_reviews(prog.review_queue, now or time.time())
    return {
        "student_id": str(student_id),
        "review_queue": [
            {
                "kc_id": t.knowledge_point_id,
                "due_at": t.due_at,
                "priority": t.priority,
            }
            for t in due
        ],
    }


def _infer_qtype(expected: str) -> str:
    """题库无 qtype 列：单字母 A/B/C/D → choice；否则 solve（grade_math sympy+回落兜底）。"""
    e = (expected or "").strip().upper().replace(" ", "")
    if 1 <= len(e) <= 3 and all(c in "ABCD、," for c in e):
        return "choice"
    return "solve"


_OPT_MARK = re.compile(r"[ABCD][.、．：)）]")


def _choice_prompt(prompt: str, qtype: str, profiler: Optional[dict]) -> str:
    """选择题：题干无选项标记时，把 profiler_analysis.options 拼回题干。

    题库录入把选项抽进了 profiler_analysis.options、没进 question_text（100% 可恢复）。
    solve/fill、或题干已含选项 → 原样返回。
    """
    if qtype != "choice" or _OPT_MARK.search(prompt):
        return prompt
    opts = str(profiler.get("options") or "") if isinstance(profiler, dict) else ""
    opts = "\n".join(ln.strip() for ln in opts.splitlines() if ln.strip())
    return f"{prompt}\n\n{opts}" if opts else prompt


async def _llm_generate_question(kc_name: str) -> Optional[dict]:
    """题库无题时 LLM(qwen)兜底：出一道题 + 标准答案。失败→None。expected 不外传。"""
    import json as _json
    import os

    key = os.environ.get("DASHSCOPE_API_KEY")
    if not key:
        return None
    try:
        from services.providers.qwenvl_caller import QwenTextCaller

        caller = QwenTextCaller(
            api_key=key, model=os.environ.get("QWEN_MODEL", "qwen-plus")
        )
        out = await caller(
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"为知识点『{kc_name}』出一道适合中学生的题，返回严格 JSON："
                        '{"prompt":"题干","answer":"标准答案","qtype":"solve"}。只输出 JSON。'
                    ),
                }
            ],
            max_tokens=512,
            response_format="json",
            enable_thinking=False,  # 出题无需思维链；避免 qwen3.x 思考模型拖慢出题(AA.8 同理)
        )
        data = _json.loads(out.get("content", "{}"))
        if data.get("prompt") and data.get("answer"):
            return {
                "prompt": str(data["prompt"]),
                "expected": str(data["answer"]),
                "qtype": str(data.get("qtype", "solve")),
            }
    except Exception:
        return None
    return None


async def tool_request_question(
    db: AsyncSession, student_id: uuid.UUID, kc_id: str
) -> dict:
    """人在环出题（S3-A poser）：为当前 KC 出下一题并登记待答；**只出不答**。

    题库(wrong_questions)优先、LLM(qwen)兜底。expected 只进 gate.pending_question，
    **绝不进返回体/prompt/LLM 上下文**。幂等：已有该 KC 的 pending 直接返回（不重复出题）。
    """
    active = await gate_store.get_active_pending(db, student_id=student_id)
    if active is not None and active["kc_id"] == kc_id:
        return {
            "question_id": active["question_id"],
            "prompt": active["prompt"],
            "qtype": active["qtype"],
            "source": "pending",
        }

    name_row = (
        await db.execute(select(KnowledgeUnit.name).where(KnowledgeUnit.id == kc_id))
    ).first()
    kc_name = name_row[0] if name_row else kc_id
    qid = f"q-{uuid.uuid4().hex}"
    gate_type = await gate_store.resolve_gate_type(db, kc_id)

    if gate_type == gate_store.QUALITATIVE:
        prompt = f"请用自己的话解释【{kc_name}】的核心概念，并举例说明。"
        await gate_store.pose_question(
            db,
            question_id=qid,
            student_id=student_id,
            kc_id=kc_id,
            prompt=prompt,
            expected=None,
            qtype="open",
        )
        return {
            "question_id": qid,
            "prompt": prompt,
            "qtype": "open",
            "source": "generated",
        }

    # 题库题清洗（serve 端，第一步）：只出**对口年级(高一)**、非图形题；选择题把 profiler
    # 里的选项拼回题干（选项 100% 在 profiler_analysis.options）。无清洁题库题 → 回落 LLM
    # 自足生成。（跨年级/跨题的错链靠后续 LLM 相关性重匹配彻底修，见 AA.9 第二步。）
    # 图形题(needs_image / <ImageHere>)仍排除：studio 无法呈现图，学生只会看到占位"标识"。
    bank = (
        await db.execute(
            select(
                WrongQuestion.question_text,
                WrongQuestion.correct_answer,
                WrongQuestion.profiler_analysis,
            )
            .where(
                WrongQuestion.knowledge_points.has_key(kc_id),
                WrongQuestion.needs_image.is_(False),
                ~WrongQuestion.question_text.like("%<ImageHere>%"),
                WrongQuestion.profiler_analysis["grade"].astext == "高一",
                # 判分红线：只出**可确定性判分**的题，否则回落 LLM（生成的 expected 干净）。
                # 题库 expected 大量是整段解析/多问（【解】/见解析/证明/(1)(2)），内核判不了、
                # 学生答对会被标错污染 BKT/FSRS。留：选择题（字母，answer_match 判）或
                # 短且无解析标记的 solve/fill。
                or_(
                    WrongQuestion.correct_answer.op("~")("^[A-D、,]{1,3}$"),
                    and_(
                        func.length(WrongQuestion.correct_answer) <= 40,
                        ~WrongQuestion.correct_answer.op("~")("解析|见解析|【解|证明"),
                        ~WrongQuestion.correct_answer.op("~")(r"[(（][1１２3３]"),
                    ),
                ),
            )
            .order_by(func.random())
            .limit(1)
        )
    ).first()
    if bank is not None and bank[0]:
        prompt, expected = str(bank[0]), str(bank[1] or "")
        qtype = _infer_qtype(expected)
        prompt = _choice_prompt(prompt, qtype, bank[2])
        source = "bank"
    else:
        gen = await _llm_generate_question(kc_name)
        if gen is None:
            return {"error": "该知识点暂无可用题目", "kc_id": kc_id}
        prompt, expected, qtype = gen["prompt"], gen["expected"], gen["qtype"]
        source = "generated"

    await gate_store.pose_question(
        db,
        question_id=qid,
        student_id=student_id,
        kc_id=kc_id,
        prompt=prompt,
        expected=expected,
        qtype=qtype,
    )
    return {"question_id": qid, "prompt": prompt, "qtype": qtype, "source": source}


async def tool_pose_question(
    db: AsyncSession,
    *,
    student_id: uuid.UUID,
    kc_id: str,
    question_id: str,
    prompt: str,
    expected: Optional[str],
    qtype: str,
) -> dict:
    """登记一道待答题；expected 落 gate.pending_question（永不外传，红线）。"""
    await gate_store.pose_question(
        db,
        question_id=question_id,
        student_id=student_id,
        kc_id=kc_id,
        prompt=prompt,
        expected=expected,
        qtype=qtype,
    )
    return {"ok": True, "question_id": question_id}


async def tool_submit_answer(
    db: AsyncSession,
    *,
    student_id: uuid.UUID,
    question_id: str,
    answer: str,
    time_spent_seconds: Optional[int] = None,
) -> dict:
    """取 pending → 判分 → guard(origin=core) → 既有 process_interaction → clear。

    判分路由（决策 D2.1）：solve/fill→grade_math(sympy)；choice/short→answer_match；
    open→needs_qualitative（零写入，交 assess→ReportResult）。
    """
    pending = await gate_store.get_pending(
        db, student_id=student_id, question_id=question_id
    )
    if pending is None:
        return {"error": "no pending question", "question_id": question_id}

    qtype = pending["qtype"]
    kc_id = pending["kc_id"]
    expected = pending["expected"] or ""

    if qtype == "open":
        # 定性题：服务端跑真 verifier（按 KC rubric 判维度 + evidence 锚定）出裁决，
        # 再走 tool_report_result 落库（gate.evidence + qualitative_mastery + clear pending），
        # 学生答完即前进。verifier 不可用（无 key/rubric/非法/LLM 失败）→ 退回 needs_qualitative
        # 交外部 assess（原行为），提交永不因 verifier 崩。
        from services.qualitative_verify import run_qualitative_verifier

        verdict = await run_qualitative_verifier(db, kc_id=kc_id, explanation=answer)
        if verdict is None:
            return {
                "needs_qualitative": True,
                "kc_id": kc_id,
                "question_id": question_id,
            }
        await tool_report_result(
            db,
            student_id=student_id,
            kc_id=kc_id,
            question_id=question_id,
            is_correct=verdict.passed,
            verdict_source="llm_verified",
            evidence=verdict.to_evidence(),
        )
        return {
            "graded": True,
            "is_correct": verdict.passed,
            "qualitative": True,
            "verdict_source": "llm_verified",
            "kc_id": kc_id,
            "score": round(verdict.score, 4),
        }

    if qtype in ("solve", "fill"):
        is_correct = grade_math(answer, expected)
    elif qtype in ("choice", "short"):
        is_correct = answer_match(answer, expected=expected, qtype=qtype).is_correct
    else:
        return {"error": f"unsupported qtype: {qtype}"}

    # guard：确定性判分由 core 产出（origin=core），杜绝 agent 伪造 deterministic
    enforce("deterministic", None, origin="core")

    # 写既有真相源（BKT/FSRS/kc_mastery/interaction_events），满足 DoD 铁律
    from services.cognitive_service import process_interaction

    await process_interaction(
        db,
        student_id=student_id,
        kc_id=kc_id,
        is_correct=is_correct,
        question_type=qtype,
        source="quick",
        student_answer=answer,
        correct_answer=expected,
        time_spent_seconds=time_spent_seconds,
    )
    await gate_store.clear_pending(db, student_id=student_id, question_id=question_id)
    return {
        "graded": True,
        "is_correct": is_correct,
        "verdict_source": "deterministic",
        "kc_id": kc_id,
    }


async def tool_report_result(
    db: AsyncSession,
    *,
    student_id: uuid.UUID,
    kc_id: str,
    question_id: Optional[str],
    is_correct: bool,
    verdict_source: str,
    evidence: Optional[dict] = None,
    response_time_ms: Optional[int] = None,
    model_id: Optional[str] = None,
) -> dict:
    """agent 上报裁决（定性主路径）。guard 先于任何写；按 gate_type 分流落库。

    - guard(origin=agent)：agent 不得 deterministic；llm_verified 必须带 evidence。
    - llm_verified → 落 gate.evidence 得 evidence_ref。
    - qualitative KC → upsert gate.qualitative_mastery；quantitative KC → 既有 process_interaction。
    """
    # llm_verified 必须带 evidence 内容（DoD：无 evidence 的 llm_verified 被拒）——
    # 在生成 evidence_ref / 任何写入之前判，保证零写入。
    if verdict_source == "llm_verified":
        if not evidence:
            raise GuardRejection("llm_verified 必须包含 evidence")
        evidence_ref: Optional[str] = uuid.uuid4().hex
    else:
        evidence_ref = None

    # 三拒（含 agent+deterministic 拒绝、source 合法性、llm_verified 需 evidence_ref）
    enforce(verdict_source, evidence_ref, origin="agent")

    if verdict_source == "llm_verified":
        await gate_store.save_evidence(
            db,
            evidence_ref=evidence_ref,  # type: ignore[arg-type]
            student_id=student_id,
            kc_id=kc_id,
            verdict=evidence,  # type: ignore[arg-type]
            model_id=model_id,
        )

    gate_type = await gate_store.resolve_gate_type(db, kc_id)
    if gate_type == gate_store.QUALITATIVE:
        await gate_store.upsert_qualitative_mastery(
            db,
            student_id=student_id,
            kc_id=kc_id,
            passed=is_correct,
            evidence_ref=evidence_ref,
        )
    else:
        # 量化 KC 经 LLM 裁决（如确定性 unsure 的短答）→ 既有 process_interaction
        from services.cognitive_service import process_interaction

        await process_interaction(
            db,
            student_id=student_id,
            kc_id=kc_id,
            is_correct=is_correct,
            question_type="open",
            source="quick",
            time_spent_seconds=(response_time_ms // 1000 if response_time_ms else None),
        )

    if question_id:
        await gate_store.clear_pending(
            db, student_id=student_id, question_id=question_id
        )

    return {
        "recorded": True,
        "kc_id": kc_id,
        "gate_type": gate_type,
        "passed": is_correct,
        "evidence_ref": evidence_ref,
    }


# ── HTTP 端点 ───────────────────────────────────────────────────────────────


class GetPathReq(BaseModel):
    student_id: uuid.UUID


class NextObjectiveReq(BaseModel):
    student_id: uuid.UUID
    kc_ids: list[str]
    now: Optional[float] = None


class GenerateQuizReq(BaseModel):
    student_id: uuid.UUID
    kc_ids: Optional[list[str]] = None
    size: int = 10
    difficulty_curve: DifficultyCurve = "ascending"
    exclude_mastered: bool = True


class GetKCInfoReq(BaseModel):
    kc_id: str


class ListPersonasReq(BaseModel):
    pass


class GetPersonaReq(BaseModel):
    slug: str


class RecallMemoryReq(BaseModel):
    student_id: uuid.UUID
    topic: Optional[str] = None


class RememberEpisodeReq(BaseModel):
    student_id: uuid.UUID
    kind: str
    content: dict
    session_id: Optional[str] = None


class SearchKnowledgeBaseReq(BaseModel):
    query: str
    top_k: int = 5


class GetReviewQueueReq(BaseModel):
    student_id: uuid.UUID
    kc_ids: list[str]
    now: Optional[float] = None


class RequestQuestionReq(BaseModel):
    student_id: uuid.UUID
    kc_id: str


class CheckMasteryReq(BaseModel):
    student_id: uuid.UUID
    kc_id: str


class PoseQuestionReq(BaseModel):
    student_id: uuid.UUID
    kc_id: str
    question_id: str
    prompt: str
    expected: Optional[str] = None
    qtype: str


class SubmitAnswerReq(BaseModel):
    student_id: uuid.UUID
    question_id: str
    answer: str
    time_spent_seconds: Optional[int] = None


class ReportResultReq(BaseModel):
    student_id: uuid.UUID
    kc_id: str
    question_id: Optional[str] = None
    is_correct: bool
    verdict_source: str
    evidence: Optional[dict] = None
    response_time_ms: Optional[int] = None
    model_id: Optional[str] = None


@router.post("/GetPath")
async def mcp_get_path(
    req: GetPathReq,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    await _ensure_student_access(db, current_user, req.student_id)
    return await tool_get_path(db, req.student_id)


@router.post("/GenerateQuiz")
async def mcp_generate_quiz(
    req: GenerateQuizReq,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    await _ensure_student_access(db, current_user, req.student_id)
    return await tool_generate_quiz(
        db,
        req.student_id,
        kc_ids=req.kc_ids,
        size=req.size,
        difficulty_curve=req.difficulty_curve,
        exclude_mastered=req.exclude_mastered,
    )


@router.post("/NextObjective")
async def mcp_next_objective(
    req: NextObjectiveReq,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    await _ensure_student_access(db, current_user, req.student_id)
    return await tool_next_objective(db, req.student_id, req.kc_ids, req.now)


@router.post("/GetKCInfo")
async def mcp_get_kc_info(
    req: GetKCInfoReq,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    # 非学生数据（KC 名/rubric），但仍要求登录：/mcp 已公网，统一"须登录"闸门。
    return await tool_get_kc_info(db, req.kc_id)


@router.post("/ListPersonas")
async def mcp_list_personas(
    req: ListPersonasReq,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    # 非学生数据（人格模板是全局固定预设），但仍要求登录：/mcp 已公网，统一"须登录"闸门。
    return await tool_list_personas(db)


@router.post("/GetPersona")
async def mcp_get_persona(
    req: GetPersonaReq,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    return await tool_get_persona(db, req.slug)


@router.post("/RecallMemory")
async def mcp_recall_memory(
    req: RecallMemoryReq,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    await _ensure_student_access(db, current_user, req.student_id)
    return await tool_recall_memory(db, req.student_id, req.topic)


@router.post("/RememberEpisode")
async def mcp_remember_episode(
    req: RememberEpisodeReq,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    _ensure_student_self(current_user, req.student_id)
    return await tool_remember_episode(
        db,
        req.student_id,
        kind=req.kind,
        content=req.content,
        session_id=req.session_id,
    )


@router.post("/SearchKnowledgeBase")
async def mcp_search_knowledge_base(
    req: SearchKnowledgeBaseReq,
    current_user: User = Depends(get_current_user),
) -> dict:
    # 非学生数据（共享知识库检索）——不碰 db，只要求登录（同 ListPersonas 惯例）。
    return await tool_search_knowledge_base(req.query, req.top_k)


@router.post("/CheckMastery")
async def mcp_check_mastery(
    req: CheckMasteryReq,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    await _ensure_student_access(db, current_user, req.student_id)
    return await tool_check_mastery(db, req.student_id, req.kc_id)


@router.post("/GetReviewQueue")
async def mcp_get_review_queue(
    req: GetReviewQueueReq,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    await _ensure_student_access(db, current_user, req.student_id)
    return await tool_get_review_queue(db, req.student_id, req.kc_ids, req.now)


@router.post("/RequestQuestion")
async def mcp_request_question(
    req: RequestQuestionReq,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    _ensure_student_self(current_user, req.student_id)
    r = await tool_request_question(db, req.student_id, req.kc_id)
    await db.commit()
    return r


@router.post("/PoseQuestion")
async def mcp_pose_question(
    req: PoseQuestionReq,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    _ensure_student_self(current_user, req.student_id)
    r = await tool_pose_question(
        db,
        student_id=req.student_id,
        kc_id=req.kc_id,
        question_id=req.question_id,
        prompt=req.prompt,
        expected=req.expected,
        qtype=req.qtype,
    )
    await db.commit()
    return r


@router.post("/SubmitAnswer")
async def mcp_submit_answer(
    req: SubmitAnswerReq,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    _ensure_student_self(current_user, req.student_id)
    try:
        r = await tool_submit_answer(
            db,
            student_id=req.student_id,
            question_id=req.question_id,
            answer=req.answer,
            time_spent_seconds=req.time_spent_seconds,
        )
        await db.commit()
        return r
    except GuardRejection as e:
        await db.rollback()
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ReportResult")
async def mcp_report_result(
    req: ReportResultReq,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    _ensure_student_self(current_user, req.student_id)
    try:
        r = await tool_report_result(
            db,
            student_id=req.student_id,
            kc_id=req.kc_id,
            question_id=req.question_id,
            is_correct=req.is_correct,
            verdict_source=req.verdict_source,
            evidence=req.evidence,
            response_time_ms=req.response_time_ms,
            model_id=req.model_id,
        )
        await db.commit()
        return r
    except GuardRejection as e:
        await db.rollback()
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
