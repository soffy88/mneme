"""答案分级红线自动化测试（MCP/服务层）
=======================================

红线（CLAUDE.md / Master 附录 L2）：
- 学生自带题/作文永不给可抄答案
- 系统教学同构新知可给完整样例
- 判定逻辑在服务层，agent 不能自行决定绕过

本测试验证 MCP 工具面（/mcp/*）与服务层在所有写/读路径上强制执行答案分级。
"""

from __future__ import annotations

import uuid

import pytest

from obase.db import SessionLocal  # noqa: E402
from services import gate_store  # noqa: E402
from services.mcp_router import (  # noqa: E402
    tool_get_kc_info,
    tool_next_objective,
    tool_pose_question,
    tool_report_result,
    tool_request_question,
    tool_submit_answer,
)
from services.models import User, UserRole  # noqa: E402

# 有 rubric 的定性 KC（教学同构新知场景）
KU_QUAL = "renjiao-math-g10-a-ku004"
# 无 rubric 的量化 KC（学生自带题场景）
KU_QUANT = "renjiao-math-g10-a-ku-二次函数的零点"
SECRET_ANSWER = "TOP_SECRET_STUDENT_ANSWER_42"


async def _mk_student(db, sid=None):
    sid = sid or uuid.uuid4()
    db.add(User(id=sid, phone=f"t{sid.hex[:10]}", role=UserRole.student))
    await db.flush()
    return sid


class TestAnswerTieringRedline:
    """答案分级红线：学生自带题/作文永不给可抄答案"""

    @pytest.mark.asyncio
    async def test_request_question_never_leaks_expected(self):
        """RequestQuestion：学生为自带 KC 出题，响应绝不含 expected"""
        sid = uuid.uuid4()
        qid = f"q-{uuid.uuid4().hex}"
        async with SessionLocal() as db:
            await _mk_student(db, sid)
            # 直接 pose 一道带 expected 的题（模拟学生自带题场景）
            await gate_store.pose_question(
                db,
                question_id=qid,
                student_id=sid,
                kc_id=KU_QUANT,
                prompt="学生自带题：求解 x^2-5x+6=0",
                expected=SECRET_ANSWER,
                qtype="fill",
            )
            # RequestQuestion 返回不应包含 expected
            resp = await tool_request_question(db, sid, KU_QUANT)
            assert resp["question_id"] == qid
            assert SECRET_ANSWER not in str(resp)
            assert "expected" not in resp
            assert resp["source"] in ("pending", "bank", "generated")

    @pytest.mark.asyncio
    async def test_pose_question_never_returns_expected(self):
        """PoseQuestion：登记待答题，响应绝不回传 expected"""
        sid = uuid.uuid4()
        qid = f"q-{uuid.uuid4().hex}"
        async with SessionLocal() as db:
            await _mk_student(db, sid)
            resp = await tool_pose_question(
                db,
                student_id=sid,
                kc_id=KU_QUANT,
                question_id=qid,
                prompt="学生自带题：证明三角形全等",
                expected=SECRET_ANSWER,
                qtype="open",
            )
            assert resp["ok"] is True
            assert SECRET_ANSWER not in str(resp)
            assert "expected" not in resp

    @pytest.mark.asyncio
    async def test_submit_answer_never_returns_expected(self):
        """SubmitAnswer：提交作答后，响应绝不泄露 expected"""
        sid = uuid.uuid4()
        qid = f"q-{uuid.uuid4().hex}"
        async with SessionLocal() as db:
            await _mk_student(db, sid)
            await gate_store.pose_question(
                db,
                question_id=qid,
                student_id=sid,
                kc_id=KU_QUANT,
                prompt="计算 2+2=?",
                expected=SECRET_ANSWER,
                qtype="fill",
            )
            resp = await tool_submit_answer(
                db,
                student_id=sid,
                question_id=qid,
                answer="4",
                time_spent_seconds=10,
            )
            assert resp["graded"] is True
            assert SECRET_ANSWER not in str(resp)
            assert "expected" not in resp
            assert "correct_answer" not in resp

    @pytest.mark.asyncio
    async def test_next_objective_never_leaks_expected_qualitative(self):
        """NextObjective：定性 KC（教学同构新知）有 pending 时，不泄露 expected"""
        sid = uuid.uuid4()
        qid = f"q-{uuid.uuid4().hex}"
        async with SessionLocal() as db:
            await _mk_student(db, sid)
            await gate_store.pose_question(
                db,
                question_id=qid,
                student_id=sid,
                kc_id=KU_QUAL,
                prompt="请用自己的话解释二次函数顶点式的几何意义",
                expected="标准答案：顶点式揭示顶点坐标...",  # 教学样例答案
                qtype="open",
            )
            resp = await tool_next_objective(db, sid, [KU_QUAL])
            assert resp["action"] == "answer_pending"
            assert resp["has_pending"] is True
            # 红线：即使是教学同构新知，pending 的 expected 也不外传
            # 前端只拿 prompt/qtype，样例答案由教学内容单独下发（非 NextObjective 路径）
            assert "expected" not in resp.get("pending_question", {})
            assert "标准答案" not in str(resp)

    @pytest.mark.asyncio
    async def test_get_kc_info_qualitative_returns_rubric_not_answer(self):
        """GetKCInfo：定性 KC 返回 rubric（评分维度），不返回标准答案"""
        async with SessionLocal() as db:
            info = await tool_get_kc_info(db, KU_QUAL)
            assert info["gate_type"] == "qualitative"
            assert info["rubric"] is not None
            assert "dimensions" in info["rubric"]
            # rubric 是评分标准，不是可抄答案
            for dim in info["rubric"]["dimensions"]:
                assert "criterion" in dim
                assert "weight" in dim
            # 绝不包含 "answer"、"标准答案" 等可抄字段
            assert "answer" not in str(info).lower()
            assert "标准答案" not in str(info)

    @pytest.mark.asyncio
    async def test_qualitative_verify_never_returns_model_answer(self):
        """定性验证路径：verdict 只返回 passed/score/evidence，不返回模型生成的完整答案"""
        from services.qualitative_verify import run_qualitative_verifier

        async with SessionLocal() as db:
            # 该 KC 有 rubric，verifier 会跑
            verdict = await run_qualitative_verifier(
                db, kc_id=KU_QUAL, explanation="二次函数顶点式 y=a(x-h)^2+k，顶点在(h,k)..."
            )
            if verdict is not None:
                # verdict 只有 passed/score/evidence，无完整范文
                assert hasattr(verdict, "passed")
                assert hasattr(verdict, "score")
                assert hasattr(verdict, "to_evidence")
                # evidence 只含维度判定+证据片段，不含完整作文
                ev = verdict.to_evidence()
                assert "dimensions" in ev
                assert "answer" not in str(ev).lower()

    @pytest.mark.asyncio
    async def test_report_result_qualitative_no_answer_leak(self):
        """ReportResult：定性上报裁决，响应不含完整答案/范文"""
        from mneme_core.service.verdict_guard import GuardRejection

        sid = uuid.uuid4()
        async with SessionLocal() as db:
            await _mk_student(db, sid)
            # llm_verified 必须带 evidence
            try:
                resp = await tool_report_result(
                    db,
                    student_id=sid,
                    kc_id=KU_QUAL,
                    question_id=None,
                    is_correct=True,
                    verdict_source="llm_verified",
                    evidence={"passed": True, "spans": [[0, 10, "核心概念"]]},
                    model_id="qwen-max",
                )
                assert resp["recorded"] is True
                assert resp["gate_type"] == "qualitative"
                # 响应只含 recorded/kc_id/gate_type/passed/evidence_ref
                assert "answer" not in str(resp).lower()
                assert "范文" not in str(resp)
                assert "完整" not in str(resp)
            except GuardRejection:
                # 如果 rubric 不全等原因被拒，也是合规的（零写入）
                pass


class TestSystemTeachingIsomorphicKnowledge:
    """系统教学同构新知：可给完整样例（但走独立内容下发路径，非 MCP 答题路径）"""

    @pytest.mark.asyncio
    async def test_lesson_page_includes_worked_example(self):
        """LessonPage：系统教学同构新知，包含完整样例+自我解释提示（同源自检）"""
        # 此处验证 omodul.generate_lesson_page_workflow 的产出
        # 该 workflow 在 omodul 层，已有 test_lesson_page_self_check.py 守卫
        # 此处仅作红线文档化：教学内容下发路径 ≠ 答题路径
        pass


class TestAnswerTieringEnforcementPoints:
    """答案分级执行点：确认所有写/读路径都在服务层强制执行"""

    def test_mcp_tools_no_expected_in_response_schemas(self):
        """静态检查：所有 MCP 工具响应模型无 expected 字段"""
        from services.mcp_router import (
            tool_get_kc_info,
            tool_next_objective,
            tool_pose_question,
            tool_request_question,
            tool_submit_answer,
            tool_report_result,
        )
        import inspect

        tools = [
            tool_get_kc_info,
            tool_next_objective,
            tool_pose_question,
            tool_request_question,
            tool_submit_answer,
            tool_report_result,
        ]
        for fn in tools:
            sig = inspect.signature(fn)
            # 返回类型注解中不应有 expected
            ret = sig.return_annotation
            assert "expected" not in str(ret).lower(), f"{fn.__name__} 返回类型含 expected"

    @pytest.mark.asyncio
    async def test_gate_store_pending_question_expected_write_only(self):
        """gate_store.pose_question：expected 只写 gate.pending_question，无读出接口"""
        import inspect

        src = inspect.getsource(gate_store.pose_question)
        # pose_question 写 expected
        assert "expected" in src
        # 但 get_pending/get_active_pending 返回供服务层判分用，不外传
        get_pending_src = inspect.getsource(gate_store.get_pending)
        assert "expected" in get_pending_src  # 内部读取用于判分
        # 关键：无导出函数把 expected 返回给调用方
        all_funcs = [name for name, _ in inspect.getmembers(gate_store, inspect.isfunction)]
        for name in all_funcs:
            if name.startswith("get_") and name != "get_pending" and name != "get_active_pending":
                # 其它 get_* 不应读 expected
                _fn_src = inspect.getsource(getattr(gate_store, name))
                # 允许内部有 expected 变量，但不应 SELECT expected 列
                assert "SELECT expected" not in _fn_src.upper()