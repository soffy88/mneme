"""tutor_loop — W2a S2 引擎装配（架构 A，FC-6 合规，无 oservi 改动）。

用 oservi 真引擎 ``oservi.agentic_loop.AgenticLoop``（on_demand 多步 ReAct ``.session()``），
经其**实例** ``.assemble()`` 注入 llm_caller + 8 callable：
  · 7 MCP 工具（NextObjective / GetKCInfo / CheckMastery / GetReviewQueue /
    PoseQuestion / SubmitAnswer / ReportResult）经 **HTTP** ``/mcp/*`` 触达；
  · t_assess_explanation：本地跑 mneme-core ``qualitative_verifier``（注入 verifier_llm）。

**agent 进程零 mneme-DB**：本模块无任何 DB import，工具全走 HTTP（FC-5）。

为何不用 oservi 模块级 ``assemble(manifest)``：该路径因 oservi 双 agentic_loop 注册
路由到不完整的 ``AgenticLoopEngine``（单轮执行、``turn_handler`` 必填），已上报 Wiki
（``OSERVI-BUG-agentic_loop-assemble.md``）。改用引擎自带**实例** ``.assemble()``——
同样对 injection_points 做校验、缺必填注入点即 ``ManifestValidationError``（W4）——
驱动真 ``.session()`` 多步循环。**禁手写循环**（循环逻辑全在引擎 session）。
"""

from __future__ import annotations

import asyncio
import json
import urllib.request
from typing import Any, Awaitable, Callable, Optional

from oservi.agentic_loop import AgenticLoop, ToolSpec

# mneme-core 纯库（无 DB）——t_assess_explanation 用
from mneme_core.oprim.models import KpView, Rubric
from mneme_core.oskill.qualitative_verifier import qualitative_verifier

DEFAULT_API_BASE = "http://localhost:8000"

# LLMCaller（qualitative_verifier 用）：messages -> JSON 文本
VerifierLLM = Callable[..., str]
# 主循环 llm_caller（引擎用）：Anthropic 风格 (messages, tools, ...) -> dict
LoopLLM = Callable[..., Awaitable[dict]]


# ── HTTP 工具客户端（零 DB，纯 HTTP，同步调用包进线程）──────────────────────


def _post_sync(url: str, payload: dict) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


async def _mcp(api_base: str, tool: str, payload: dict) -> dict:
    """POST {api_base}/mcp/{tool}；422（guard 三拒）等经异常体返回给 LLM 观察。"""
    try:
        return await asyncio.to_thread(_post_sync, f"{api_base}/mcp/{tool}", payload)
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
) -> list[ToolSpec]:
    """构造 8 个 ToolSpec。student_id/kc_ids/api_base 绑进闭包（会话上下文，不由 LLM 提供）。"""

    async def next_objective(inp: dict) -> Any:
        return await _mcp(
            api_base, "NextObjective", {"student_id": student_id, "kc_ids": kc_ids}
        )

    async def get_kc_info(inp: dict) -> Any:
        return await _mcp(api_base, "GetKCInfo", {"kc_id": inp["kc_id"]})

    async def check_mastery(inp: dict) -> Any:
        return await _mcp(
            api_base, "CheckMastery", {"student_id": student_id, "kc_id": inp["kc_id"]}
        )

    async def get_review_queue(inp: dict) -> Any:
        return await _mcp(
            api_base, "GetReviewQueue", {"student_id": student_id, "kc_ids": kc_ids}
        )

    async def pose_question(inp: dict) -> Any:
        return await _mcp(
            api_base,
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
        return await _mcp(
            api_base,
            "SubmitAnswer",
            {
                "student_id": student_id,
                "question_id": inp["question_id"],
                "answer": inp["answer"],
            },
        )

    async def report_result(inp: dict) -> Any:
        return await _mcp(
            api_base,
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
        info = await _mcp(api_base, "GetKCInfo", {"kc_id": inp["kc_id"]})
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
    ]


def build_tutor_loop(
    *,
    api_base: str = DEFAULT_API_BASE,
    student_id: str,
    kc_ids: list[str],
    llm_caller: LoopLLM,
    verifier_llm: Optional[VerifierLLM] = None,
    max_iterations: int = 40,
    budget_usd: float = 5.0,
) -> AgenticLoop:
    """装配 on_demand tutor 引擎：真 oservi AgenticLoop + 实例 .assemble() 注入点校验。

    Returns 已装配、可 ``await loop.session(task=...)`` 的引擎。缺必填注入点 → ManifestValidationError。
    """
    tools = build_tools(
        api_base, student_id=student_id, kc_ids=kc_ids, verifier_llm=verifier_llm
    )
    from pathlib import Path

    loop = AgenticLoop(
        max_iterations=max_iterations,
        model="tutor",
        mode="build",
        output_dir=Path("/tmp/mneme_tutor"),
        budget_usd=budget_usd,
    )
    loop.assemble(llm_caller=llm_caller, tools=tools)  # 校验注入点（W4）
    return loop
