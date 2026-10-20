"""tutor_loop — Mneme chat 的 MCP 工具装配（FC-5，零 DB）。

用仓内 ``LocalAgenticLoop``（on_demand 多步工具调用 ``.session()``），注入
llm_caller + 12 callable：
  · 11 MCP 工具（NextObjective / GetKCInfo / CheckMastery / GetReviewQueue /
    PoseQuestion / SubmitAnswer / ReportResult / RecallMemory / RememberEpisode /
    SearchKnowledgeBase / SearchTextbookKnowledge，C5 起加 Recall/Remember、
    C4 起加 SearchKnowledgeBase、W3 A4 起加 SearchTextbookKnowledge）
    经 **HTTP** ``/mcp/*`` 触达；
  · 4 个先修回溯诊断工具（CNM-3：SearchMathTopic / GetMathTopic / StartPrereqDiagnosis /
    SubmitPrereqDiagnosisAnswer），同样走 HTTP；授权见 services.tool_grants（学生默认放行，
    admin 可经 SetUserGrant 收紧）。诊断会话 JSON 由 agent 原样回传；学生作答由服务端逐题经
    SubmitAnswer 写路径回写掌握度，agent 不得自行判定掌握度、不得用 result 自评代学生作答；
  · GenerateKUVisualization（AetherViz 知识点互动课，单文件 HTML，按 KU 缓存；学生默认放行；
    status=pending 时稍后同参重调）；HTML 只给前端 sandbox iframe，agent 只引用 ku_id/题目；
  · t_assess_explanation：本地跑 mneme-core ``qualitative_verifier``（注入 verifier_llm）。

Recall/RememberEpisode（C5）/SearchKnowledgeBase（C4）/SearchTextbookKnowledge（W3 A4）：
memory/RAG/Knowledge Hub 都是呈现层上下文，不进门控判据——四个工具只读写
`agent.*` schema、代理 Stratum 检索、或查询 Mneme 自建教材语料，与
kc_mastery/gate.* 无关，不影响任何过门判定。

**agent 进程零 mneme-DB**：本模块无任何 DB import，工具全走 HTTP（FC-5）。

循环骨架只处理 provider 的文本/工具调用协议，不持久化会话状态；Mneme 业务能力
仍全部通过 HTTP MCP 工具注入。这样 chat 在没有可选 oservi 挂载时也能启动。
"""

from __future__ import annotations

import asyncio
import json
import urllib.request
from typing import Any, Awaitable, Callable, Optional

from mneme_agent.assembly.local_agentic_loop import LocalAgenticLoop, ToolSpec

# mneme-core 纯库（无 DB）——t_assess_explanation 用
from mneme_core.domain.oprim.models import KpView, Rubric
from mneme_core.domain.oskill.qualitative_verifier import qualitative_verifier
from mneme_core.tutor_control import (
    TutorObservation,
    decide_tutor_move,
    sanitize_tutor_output,
)

DEFAULT_API_BASE = "http://localhost:8000"

# LLMCaller（qualitative_verifier 用）：messages -> JSON 文本
VerifierLLM = Callable[..., str]
# 主循环 llm_caller（引擎用）：Anthropic 风格 (messages, tools, ...) -> dict
LoopLLM = Callable[..., Awaitable[dict]]
OutputGuard = Callable[[str], str]


# ── HTTP 工具客户端（零 DB，纯 HTTP，同步调用包进线程）──────────────────────


def _post_sync(url: str, payload: dict, auth_token: Optional[str] = None) -> dict:
    headers = {"Content-Type": "application/json"}
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


async def _mcp(
    api_base: str, tool: str, payload: dict, *, auth_token: Optional[str] = None
) -> dict:
    """POST {api_base}/mcp/{tool}；422（guard 三拒）等经异常体返回给 LLM 观察。

    auth_token：/mcp/* 自 AA.1 起每端点要求 JWT（关 IDOR）；不带 token 一律 401。
    调用方（build_tools）把发起这轮会话的学生自己的 token 绑进闭包传下来。
    """
    try:
        return await asyncio.to_thread(
            _post_sync, f"{api_base}/mcp/{tool}", payload, auth_token
        )
    except urllib.error.HTTPError as e:  # noqa: PERF203
        body = e.read().decode("utf-8", "replace")
        return {"error": f"HTTP {e.code}", "detail": body}


# ── 8 callable（7 HTTP + t_assess_explanation）——绑定会话上下文 ────────────


def build_tools(
    api_base: str,
    *,
    student_id: str,
    kc_ids: list[str],
    verifier_llm: Optional[VerifierLLM] = None,
    auth_token: Optional[str] = None,
) -> list[ToolSpec]:
    """构造 8 个 ToolSpec。student_id/kc_ids/api_base/auth_token 绑进闭包（会话
    上下文，不由 LLM 提供）。auth_token：/mcp/* 自 AA.1 起每端点要求 JWT，这里
    传发起本轮会话的学生自己的 token（同一份，不单独铸造）。"""

    async def _call(tool: str, payload: dict) -> Any:
        return await _mcp(api_base, tool, payload, auth_token=auth_token)

    async def next_objective(inp: dict) -> Any:
        return await _call(
            "NextObjective", {"student_id": student_id, "kc_ids": kc_ids}
        )

    async def get_kc_info(inp: dict) -> Any:
        return await _call("GetKCInfo", {"kc_id": inp["kc_id"]})

    async def check_mastery(inp: dict) -> Any:
        return await _call(
            "CheckMastery", {"student_id": student_id, "kc_id": inp["kc_id"]}
        )

    async def get_review_queue(inp: dict) -> Any:
        return await _call(
            "GetReviewQueue", {"student_id": student_id, "kc_ids": kc_ids}
        )

    async def pose_question(inp: dict) -> Any:
        return await _call(
            "PoseQuestion",
            {
                "student_id": student_id,
                "kc_id": inp["kc_id"],
                "question_id": inp["question_id"],
                "prompt": inp["prompt"],
                "expected": inp.get("expected"),
                "qtype": inp["qtype"],
            },
        )

    async def submit_answer(inp: dict) -> Any:
        return await _call(
            "SubmitAnswer",
            {
                "student_id": student_id,
                "question_id": inp["question_id"],
                "answer": inp["answer"],
            },
        )

    async def report_result(inp: dict) -> Any:
        return await _call(
            "ReportResult",
            {
                "student_id": student_id,
                "kc_id": inp["kc_id"],
                "question_id": inp.get("question_id"),
                "is_correct": inp["is_correct"],
                "verdict_source": inp["verdict_source"],
                "evidence": inp.get("evidence"),
                "model_id": inp.get("model_id"),
            },
        )

    async def t_assess_explanation(inp: dict) -> Any:
        """本地定性评判：GetKCInfo 取 rubric → qualitative_verifier(注入 verifier_llm) → verdict。"""
        if verifier_llm is None:
            return {"error": "verifier_llm 未注入，无法定性评判"}
        info = await _call("GetKCInfo", {"kc_id": inp["kc_id"]})
        rubric_dict = info.get("rubric")
        if not rubric_dict:
            return {
                "error": "该 KC 无 rubric，不可 assess（fail-safe）",
                "kc_id": inp["kc_id"],
            }
        rubric = Rubric.from_dict(rubric_dict)
        kp = KpView(
            kc_id=inp["kc_id"],
            name=info.get("name", inp["kc_id"]),
            gate_type=info.get("gate_type", "qualitative"),
        )
        verdict = qualitative_verifier(
            inp["explanation"], rubric=rubric, kp=kp, llm=verifier_llm
        )
        return {
            "passed": verdict.passed,
            "score": verdict.score,
            "evidence": verdict.to_evidence(),
        }

    async def recall_memory(inp: dict) -> Any:
        """C5：召回呈现层记忆上下文（不影响门控/判分）。"""
        return await _call(
            "RecallMemory", {"student_id": student_id, "topic": inp.get("topic")}
        )

    async def remember_episode(inp: dict) -> Any:
        """C5：记一条 episodic 记忆（只增不改）。"""
        return await _call(
            "RememberEpisode",
            {
                "student_id": student_id,
                "kind": inp["kind"],
                "content": inp["content"],
                "session_id": inp.get("session_id"),
            },
        )

    async def search_knowledge_base(inp: dict) -> Any:
        """C4：检索 Stratum 知识库素材（呈现层，不影响门控/判分）。"""
        return await _call(
            "SearchKnowledgeBase",
            {"query": inp["query"], "top_k": inp.get("top_k", 5)},
        )

    async def search_textbook_knowledge(inp: dict) -> Any:
        """W3 A4：检索 Mneme 自建 Knowledge Hub（教材 chunk，带出处，呈现层，不影响
        门控/判分）。kc_id 与 query 二选一；结果永远带 score + provenance="inferred"，
        不只返回第一名——调用方自行判断是否够可信，本工具不代为决定。
        """
        return await _call(
            "SearchTextbookKnowledge",
            {
                "kc_id": inp.get("kc_id"),
                "query": inp.get("query"),
                "top_k": inp.get("top_k", 3),
            },
        )

    async def search_math_topic(inp: dict) -> Any:
        """CNM-3：检索一—九年级数学知识点（cn-math-taxonomy 共享知识图，只读）。"""
        return await _call(
            "SearchMathTopic", {"q": inp["q"], "limit": inp.get("limit", 10)}
        )

    async def get_math_topic(inp: dict) -> Any:
        return await _call(
            "GetMathTopic",
            {
                "topic_id": inp["topic_id"],
                "recursive_prereqs": bool(inp.get("recursive_prereqs", False)),
            },
        )

    async def start_prereq_diagnosis(inp: dict) -> Any:
        return await _call(
            "StartPrereqDiagnosis",
            {"targets": inp["targets"], "limit": inp.get("limit")},
        )

    async def submit_prereq_diagnosis_answer(inp: dict) -> Any:
        """学生作答原样转交；result 只在学生本人明确自评/说不会时给。"""
        return await _call(
            "SubmitPrereqDiagnosisAnswer",
            {
                "session": inp["session"],
                "answer": inp.get("answer"),
                "result": inp.get("result"),
            },
        )

    async def generate_ku_visualization(inp: dict) -> Any:
        """AetherViz：为知识点生成/取缓存互动课；返回值去掉 html（太长，前端另取）。"""
        out = await _call(
            "GenerateKUVisualization",
            {"ku_id": inp["ku_id"], "weak_points": inp.get("weak_points"), "wait_seconds": 20},
        )
        if isinstance(out, dict) and "html" in out:
            out = {k: v for k, v in out.items() if k != "html"}
            out["html_available"] = True
        return out

    def _spec(fn, name, desc, props, required, readonly=False) -> ToolSpec:
        return ToolSpec(
            name=name,
            description=desc,
            input_schema={"type": "object", "properties": props, "required": required},
            callable=fn,
            readonly=readonly,
        )

    return [
        _spec(
            next_objective,
            "NextObjective",
            "取该学生下一步学习目标（pending/review/practice/assess/complete）",
            {},
            [],
            readonly=True,
        ),
        _spec(
            get_kc_info,
            "GetKCInfo",
            "取 KC 元数据 + gate_type + rubric（若定性）",
            {"kc_id": {"type": "string"}},
            ["kc_id"],
            readonly=True,
        ),
        _spec(
            check_mastery,
            "CheckMastery",
            "取该 KC 掌握度快照（p_learned/下界/is_mastered）",
            {"kc_id": {"type": "string"}},
            ["kc_id"],
            readonly=True,
        ),
        _spec(
            get_review_queue,
            "GetReviewQueue",
            "取到期复习队列（priority 升序）",
            {},
            [],
            readonly=True,
        ),
        _spec(
            pose_question,
            "PoseQuestion",
            "登记一道待答题（expected 只存服务端，永不外传）",
            {
                "kc_id": {"type": "string"},
                "question_id": {"type": "string"},
                "prompt": {"type": "string"},
                "expected": {"type": "string"},
                "qtype": {
                    "type": "string",
                    "enum": ["solve", "fill", "choice", "short", "open"],
                },
            },
            ["kc_id", "question_id", "prompt", "qtype"],
        ),
        _spec(
            submit_answer,
            "SubmitAnswer",
            "提交作答，确定性判分（solve/fill→sympy，choice/short→match，open→需定性）",
            {"question_id": {"type": "string"}, "answer": {"type": "string"}},
            ["question_id", "answer"],
        ),
        _spec(
            report_result,
            "ReportResult",
            "上报裁决（定性主路径 llm_verified 必带 evidence；agent 不得 deterministic）",
            {
                "kc_id": {"type": "string"},
                "question_id": {"type": "string"},
                "is_correct": {"type": "boolean"},
                "verdict_source": {"type": "string"},
                "evidence": {"type": "object"},
                "model_id": {"type": "string"},
            },
            ["kc_id", "is_correct", "verdict_source"],
        ),
        _spec(
            t_assess_explanation,
            "AssessExplanation",
            "对开放自我解释按 rubric 定性评判 + evidence_spans 锚定",
            {"kc_id": {"type": "string"}, "explanation": {"type": "string"}},
            ["kc_id", "explanation"],
        ),
        _spec(
            recall_memory,
            "RecallMemory",
            "召回该学生的呈现层记忆背景（不影响门控/判分，仅供对话参考）",
            {"topic": {"type": "string"}},
            [],
            readonly=True,
        ),
        _spec(
            remember_episode,
            "RememberEpisode",
            "记一条本轮对话的记忆（只增不改，供后续沉淀摘要用）",
            {
                "kind": {"type": "string"},
                "content": {"type": "object"},
                "session_id": {"type": "string"},
            },
            ["kind", "content"],
        ),
        _spec(
            search_knowledge_base,
            "SearchKnowledgeBase",
            "检索知识库素材（先 Stratum，无结果时回落 Mneme 教材库，结果带书名/页码；"
            "呈现层参考，不影响门控/判分；都不可用时返回空列表）",
            {
                "query": {"type": "string"},
                "top_k": {"type": "integer"},
            },
            ["query"],
            readonly=True,
        ),
        _spec(
            search_textbook_knowledge,
            "SearchTextbookKnowledge",
            "检索 Mneme 自建 Knowledge Hub 教材内容（带出处：pdf_id/页码/字符区间；"
            "kc_id 或 query 二选一；结果为推断挂接/语义检索，带 score，非权威）",
            {
                "kc_id": {"type": "string"},
                "query": {"type": "string"},
                "top_k": {"type": "integer"},
            },
            [],
            readonly=True,
        ),
        _spec(
            search_math_topic,
            "SearchMathTopic",
            "按名称/描述检索一—九年级数学知识点（返回 KU id cnmath:cnm_xxx、年级、章节）",
            {"q": {"type": "string"}, "limit": {"type": "integer"}},
            ["q"],
            readonly=True,
        ),
        _spec(
            get_math_topic,
            "GetMathTopic",
            "取数学知识点详情 + 直接先修（hard/soft）；recursive_prereqs=true 给全部祖先",
            {
                "topic_id": {"type": "string"},
                "recursive_prereqs": {"type": "boolean"},
            },
            ["topic_id"],
            readonly=True,
        ),
        _spec(
            start_prereq_diagnosis,
            "StartPrereqDiagnosis",
            "对目标知识点开先修回溯诊断（每点≤2题，答错沿先修回溯找薄弱根因）；"
            "返回 session（原样保存回传）+ 第一题（不含答案）",
            {
                "targets": {"type": "array", "items": {"type": "string"}},
                "limit": {"type": "integer"},
            },
            ["targets"],
        ),
        _spec(
            submit_prereq_diagnosis_answer,
            "SubmitPrereqDiagnosisAnswer",
            "交学生对当前诊断题的原话作答（session 原样回传）；返回下一题与报告"
            "（薄弱根因 + 按年级学习路径）。作答由服务端判分并经 SubmitAnswer 回写掌握度；"
            "needs_self_assessment=true 时请学生本人自评后带 result 重交",
            {
                "session": {"type": "object"},
                "answer": {"type": "string"},
                "result": {"type": "string", "enum": ["correct", "wrong", "skip"]},
            },
            ["session"],
        ),
        _spec(
            generate_ku_visualization,
            "GenerateKUVisualization",
            "为一个知识点（KU id，如 cnmath:cnm_148）生成互动可视化课（单文件 HTML，前端沙箱展示），"
            "可带诊断薄弱点；返回 status=ready/pending/failed 与课内测验题目（不含答案）。"
            "pending 表示正在生成，稍后同参再调；测验作答由前端经 SubmitAnswer 路径回写，agent 不代答",
            {
                "ku_id": {"type": "string"},
                "weak_points": {"type": "array", "items": {"type": "string"}},
            },
            ["ku_id"],
        ),
    ]


def build_tutor_loop(
    *,
    api_base: str = DEFAULT_API_BASE,
    student_id: str,
    kc_ids: list[str],
    llm_caller: LoopLLM,
    verifier_llm: Optional[VerifierLLM] = None,
    auth_token: Optional[str] = None,
    max_iterations: int = 40,
    budget_usd: float = 5.0,
    output_guard: Optional[OutputGuard] = None,
    tutor_context: str = "stuck",
    learner_stage: Optional[str] = None,
    independent_mode: bool = False,
    answer_seen: bool = False,
    protected_answer: str = "",
) -> LocalAgenticLoop:
    """装配无外部引擎依赖的 on-demand tutor loop。

    auth_token：/mcp/* 自 AA.1 起每端点要求 JWT（关 IDOR），不带 token 工具调用一律
    401。传发起本轮会话的学生自己的 token（调用方在鉴权时已拿到，这里只转发，不
    单独铸造）。

    Returns 已装配、可 ``await loop.session(task=...)`` 的内存循环。
    """
    tools = build_tools(
        api_base,
        student_id=student_id,
        kc_ids=kc_ids,
        verifier_llm=verifier_llm,
        auth_token=auth_token,
    )
    from pathlib import Path

    control = decide_tutor_move(
        TutorObservation(
            context=tutor_context,
            learner_stage=learner_stage,
            # The agent-side default is conservative.  The API policy remains
            # the authority for enabling a worked example; this flag only
            # selects the output guard for the already-authorized session.
            engine_enabled=True,
            independent_mode=independent_mode,
            answer_seen=answer_seen,
        )
    )

    def default_output_guard(text: str) -> str:
        return sanitize_tutor_output(
            text,
            protected_answer=protected_answer,
            decision=control,
        ).text

    loop = LocalAgenticLoop(
        max_iterations=max_iterations,
        model="tutor",
        mode="build",
        output_dir=Path("/tmp/mneme_tutor"),
        budget_usd=budget_usd,
    )
    loop.assemble(
        llm_caller=llm_caller,
        tools=tools,
        output_guard=output_guard or default_output_guard,
    )  # 校验注入点（W4）
    return loop
