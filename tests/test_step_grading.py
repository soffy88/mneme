"""T.6 拍卷过程批改：OCR 步骤 × verify_step 确定性链。

覆盖：
- 红线：错误中间步由 verify_step 确定性定位（0-based first_wrong_step），
  全程无 LLM 参与判步；
- 步骤证据 → careless/dontknow 平局判定（只在两假设权重近平局时改判，
  红线公式 careless∝P(L)·P(S) 权威性不被推翻）；
- 无步骤题行为与基线一致；
- OCR 输出契约 student_steps（Mock VLM 路径）；
- analyze_paper 全链（Mock OCR → 批改 → step_analysis 落库 → 认知更新）。
"""

import uuid

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from obase.cognitive_types import KCState, fsrs_new_card
from obase.config import settings
from obase.llm import register_mock_providers
from oprim.bkt import error_weights
from oskill.cognitive_state import CognitiveUpdateInput, cognitive_update
from oskill.paper_grading import (
    _step_evidence_from_chain,
    process_single_question,
    verify_steps_chain,
)
from services.models import User, UserRole, WrongQuestion

engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
SessionLocal = async_sessionmaker(
    bind=engine, class_=AsyncSession, expire_on_commit=False
)

# 4 步，第 2 步（0-based index 1）引入代数错误：x²=4 ⇒ x=3
FOUR_STEPS = ["x**2 = 4", "x = 3", "x + 1 = 4", "3 + 1 = 4"]


@pytest.fixture(autouse=True)
def setup_mock_llm():
    try:
        register_mock_providers()
    except Exception:
        pass


@pytest.fixture
async def test_student():
    async with SessionLocal() as session:
        student_id = uuid.uuid4()
        user = User(
            id=student_id, phone=f"198{str(uuid.uuid4())[:8]}", role=UserRole.student
        )
        session.add(user)
        await session.commit()

        yield student_id

        await session.execute(
            delete(WrongQuestion).where(WrongQuestion.student_id == student_id)
        )
        await session.execute(delete(User).where(User.id == student_id))
        await session.commit()


# ── 红线：verify_step 确定性定位首个错步，无 LLM ────────────────────────────


def test_steps_chain_locates_first_wrong_step_without_llm(monkeypatch):
    """红线：第 2 步（0-based index 1）的代数错误由 verify_step 链定位；
    ProviderRegistry 被替换为"一碰就炸"仍能判步 → 证明全程无 LLM 参与。"""
    from obase.provider_registry import ProviderRegistry

    def _forbidden(*args, **kwargs):
        raise AssertionError("LLM/VLM must not be called during step verification")

    monkeypatch.setattr(ProviderRegistry, "get", _forbidden)

    res = verify_steps_chain(FOUR_STEPS)
    verdicts = [v["verdict"] for v in res["step_verdicts"]]
    assert verdicts == ["unknown", "wrong", "unknown", "ok"]
    assert res["first_wrong_step"] == 1  # 0-based
    assert [v["step_text"] for v in res["step_verdicts"]] == FOUR_STEPS


def test_steps_chain_correct_assignment_and_arithmetic():
    """正确代回（x=2 满足 x²=4）与正确算术 → 无错步。"""
    res = verify_steps_chain(["x**2 = 4", "x = 2", "2 + 2 = 4"])
    verdicts = [v["verdict"] for v in res["step_verdicts"]]
    assert verdicts == ["unknown", "ok", "ok"]
    assert res["first_wrong_step"] is None


def test_steps_chain_arithmetic_error_and_unicode():
    """纯算术错误直接判 wrong；上标/×÷ 归一后可判（OCR 常见形态）。"""
    res = verify_steps_chain(["2 + 3 = 6"])
    assert res["step_verdicts"][0]["verdict"] == "wrong"
    assert res["first_wrong_step"] == 0

    res2 = verify_steps_chain(["x² = 4", "x = 3"])
    assert res2["step_verdicts"][1]["verdict"] == "wrong"
    assert res2["first_wrong_step"] == 1


def test_steps_chain_unknown_boundaries():
    """能力边界：一般含变量变形/多变量/不可解析/空列表 → unknown，不误伤。"""
    res = verify_steps_chain(["2*x = 6", "x + 1 = 4", "y + z = 1", "看图可知"])
    assert [v["verdict"] for v in res["step_verdicts"]] == ["unknown"] * 4
    assert res["first_wrong_step"] is None

    empty = verify_steps_chain([])
    assert empty["step_verdicts"] == []
    assert empty["first_wrong_step"] is None


# ── 步骤证据映射规则 ─────────────────────────────────────────────────────────


def test_step_evidence_mapping_rules():
    # 全对（或 unknown）且至少一步 ok、末答仍错 → careless 倾向
    ch = verify_steps_chain(["x**2 = 4", "x = 2", "2 + 2 = 4"])
    assert _step_evidence_from_chain(ch) == "careless"
    # 仅末步错 → careless 倾向
    ch_last = verify_steps_chain(["x**2 = 4", "x = 2", "2 + 2 = 5"])
    assert ch_last["first_wrong_step"] == 2
    assert _step_evidence_from_chain(ch_last) == "careless"
    # 首错步在前 1/3（index 1 < 4/3）→ dontknow 倾向
    assert _step_evidence_from_chain(verify_steps_chain(FOUR_STEPS)) == "dontknow"
    # 中段错（index 2，n=6：2 >= 6/3 且非末步）→ 不给证据
    ch_mid = verify_steps_chain(
        ["1 + 1 = 2", "x**2 = 4", "x = 3", "a + b = 1", "c + d = 2", "2 + 2 = 4"]
    )
    assert ch_mid["first_wrong_step"] == 2
    assert _step_evidence_from_chain(ch_mid) is None
    # 全 unknown → 不给证据
    assert _step_evidence_from_chain(verify_steps_chain(["x + y = 4"])) is None


# ── careless/dontknow 平局判定（不改红线公式）────────────────────────────────


def _run_update(p_init: float, evidence: str | None):
    state = KCState(
        kc_id="T6-KC", p_init=p_init, p_transit=0.0, p_guess=0.2, p_slip=0.2
    )
    return cognitive_update(
        input=CognitiveUpdateInput(
            state=state,
            card_dict=fsrs_new_card(),
            is_correct=False,
            step_evidence=evidence,
        )
    )


def test_step_evidence_breaks_near_tie_toward_careless():
    """步骤全对/仅末步错的证据：在两假设权重近平局时把 dontknow 改判 careless。"""
    base = _run_update(0.934, None)
    assert base.error_type == "dontknow"
    cw, dw = error_weights(state=base.state)
    assert min(cw, dw) / max(cw, dw) >= 0.8  # 前提：近平局

    res = _run_update(0.934, "careless")
    assert res.error_type == "careless"


def test_step_evidence_breaks_near_tie_toward_dontknow():
    """前段即错的证据：近平局时把 careless 改判 dontknow。"""
    base = _run_update(0.948, None)
    assert base.error_type == "careless"
    cw, dw = error_weights(state=base.state)
    assert min(cw, dw) / max(cw, dw) >= 0.8

    res = _run_update(0.948, "dontknow")
    assert res.error_type == "dontknow"


def test_step_evidence_cannot_override_decisive_classification():
    """红线：careless∝P(L)·P(S) 判定悬殊时，步骤证据不可推翻 BKT 分类。"""
    base = _run_update(0.2, None)
    assert base.error_type == "dontknow"
    cw, dw = error_weights(state=base.state)
    assert min(cw, dw) / max(cw, dw) < 0.8  # 前提：权重悬殊

    res = _run_update(0.2, "careless")
    assert res.error_type == "dontknow"  # 不被推翻


def test_step_evidence_none_keeps_baseline():
    """step_evidence 缺省（None）→ 与基线逐位一致（状态与分类均不变）。"""
    a = _run_update(0.934, None)
    b = _run_update(0.934, None)
    assert a.error_type == b.error_type == "dontknow"
    assert a.state.p_mastery == b.state.p_mastery


# ── 批改路径：落库与无步骤基线 ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_process_single_question_persists_step_analysis(test_student):
    async with SessionLocal() as session:
        res = await process_single_question(
            session=session,
            student_id=test_student,
            paper_id=None,
            question_text="解方程 x²=4，求 x",
            student_answer="x = 3",
            correct_answer="x = 2 或 x = -2",
            student_steps=FOUR_STEPS,
        )
        assert res["status"] == "wrong"
        assert res["first_wrong_step"] == 1
        assert [v["verdict"] for v in res["step_verdicts"]] == [
            "unknown",
            "wrong",
            "unknown",
            "ok",
        ]
        assert res["step_evidence"] == "dontknow"
        await session.commit()

        wq = (
            await session.execute(
                select(WrongQuestion).where(WrongQuestion.id == uuid.UUID(res["wq_id"]))
            )
        ).scalar_one()
        assert wq.step_analysis is not None
        assert wq.step_analysis["first_wrong_step"] == 1
        assert wq.step_analysis["student_steps"] == FOUR_STEPS
        assert wq.step_analysis["step_verdicts"][1]["verdict"] == "wrong"


@pytest.mark.asyncio
async def test_process_single_question_no_steps_baseline(test_student):
    """无步骤题：结果不含 step 字段、step_analysis 落 NULL——行为与基线一致。"""
    async with SessionLocal() as session:
        res = await process_single_question(
            session=session,
            student_id=test_student,
            paper_id=None,
            question_text="1+1=?",
            student_answer="3",
            correct_answer="2",
        )
        assert res["status"] == "wrong"
        assert "step_verdicts" not in res
        assert "first_wrong_step" not in res
        assert "step_evidence" not in res
        await session.commit()

        wq = (
            await session.execute(
                select(WrongQuestion).where(WrongQuestion.id == uuid.UUID(res["wq_id"]))
            )
        ).scalar_one()
        assert wq.step_analysis is None


# ── OCR 输出契约（Mock VLM 路径）────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ocr_paper_mock_vlm_student_steps():
    """Mock VLM 罐头题目：student_steps 原样透出；缺失时归一为 []。"""
    canned = [
        {
            "no": "1",
            "question_text": "x²=4",
            "student_answer": "x=3",
            "correct_answer": "x=±2",
            "student_steps": ["x² = 4", "x = 3"],
        },
        {
            "no": "2",
            "question_text": "1+1=?",
            "student_answer": "2",
            "correct_answer": "2",
        },
    ]
    register_mock_providers(vlm_questions=canned)
    try:
        from oprim.llm_oprims import ocr_paper

        res = await ocr_paper(image_b64="fake_b64")
        assert len(res.questions) == 2
        assert res.questions[0]["student_steps"] == ["x² = 4", "x = 3"]
        assert res.questions[1]["student_steps"] == []
    finally:
        register_mock_providers(vlm_questions=[])  # 还原为空 questions Mock


# ── analyze_paper 全链（Mock OCR → 真实批改 → 落库 + 认知更新）──────────────


@pytest.fixture
async def paper_context():
    from services.models import (
        InteractionEvent,
        KCMastery,
        Paper,
        PaperStatus,
    )

    async with SessionLocal() as session:
        student_id = uuid.uuid4()
        user = User(
            id=student_id, phone=f"197{str(uuid.uuid4())[:8]}", role=UserRole.student
        )
        session.add(user)
        await session.flush()

        paper_id = uuid.uuid4()
        paper = Paper(id=paper_id, student_id=student_id, status=PaperStatus.processing)
        session.add(paper)
        await session.commit()

        yield session, student_id, paper_id

        await session.execute(
            delete(InteractionEvent).where(InteractionEvent.student_id == student_id)
        )
        await session.execute(
            delete(KCMastery).where(KCMastery.student_id == student_id)
        )
        await session.execute(
            delete(WrongQuestion).where(WrongQuestion.student_id == student_id)
        )
        from services.models import Paper as PaperModel

        await session.execute(delete(PaperModel).where(PaperModel.id == paper_id))
        await session.execute(delete(User).where(User.id == student_id))
        await session.commit()


@pytest.mark.asyncio
async def test_analyze_paper_full_path_with_steps(paper_context):
    """Mock OCR 出 4 步（第 2 步错）→ 真实批改链定位错步、step_analysis 落库、
    认知更新照常发生。"""
    from unittest.mock import AsyncMock, patch

    from obase.cognitive_store import PgStore
    from obase.prior_provider import PriorProvider
    from omodul.analyze_paper import (
        AnalyzePaperConfig,
        AnalyzePaperInput,
        analyze_paper_workflow,
    )
    from oprim.llm_oprims import PaperOCRResult

    session, student_id, paper_id = paper_context

    mock_ocr_res = PaperOCRResult(
        questions=[
            {
                "no": "1",
                "question_text": "解方程 x²=4，求 x",
                "student_answer": "x = 3",
                "correct_answer": "x = 2 或 x = -2",
                "student_steps": FOUR_STEPS,
            }
        ],
        raw_text="Fake OCR with steps",
    )

    with patch("omodul.analyze_paper.ocr_paper", AsyncMock(return_value=mock_ocr_res)):
        await PriorProvider.warm_up(session)
        result = await analyze_paper_workflow(
            AnalyzePaperConfig(),
            AnalyzePaperInput(
                paper_id=paper_id, student_id=student_id, image_b64_list=["fake_b64"]
            ),
            PgStore(session),
            session,
        )

    assert result["status"] == "completed"
    findings = result["findings"]
    assert findings.wrong_count == 1
    wq_res = findings.wrong_questions[0]
    assert wq_res["first_wrong_step"] == 1  # 0-based：第 2 步引入的代数错误
    assert [v["verdict"] for v in wq_res["step_verdicts"]] == [
        "unknown",
        "wrong",
        "unknown",
        "ok",
    ]
    assert wq_res["step_evidence"] == "dontknow"
    assert len(findings.cognitive_updates) >= 1  # 认知更新照常发生

    wq = (
        await session.execute(
            select(WrongQuestion).where(WrongQuestion.id == uuid.UUID(wq_res["wq_id"]))
        )
    ).scalar_one()
    assert wq.step_analysis is not None
    assert wq.step_analysis["first_wrong_step"] == 1
