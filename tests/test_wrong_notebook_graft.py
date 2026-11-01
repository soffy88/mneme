"""wrong-notebook 双嫁接测试：组卷打印闭环 + SVG 动画讲解环。

只连 mneme_test（db_guard 钉死），绝不碰生产库。
固件按迁移同源 DDL 自建三张表（IF NOT EXISTS，仅测试库）；迁移
upgrade/downgrade 真跑走克隆库模式，见 test_migration_upgrades_to_single_head。
"""

from __future__ import annotations

import io
import uuid
import zipfile
from xml.etree import ElementTree as ET

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from services.animated_explanation import (
    animation_provenance,
    assemble_animation,
    linear_shift_spec,
    pythagorean_spec,
    verify_animation,
)
from services.exam_sheet import (
    assemble_exam_sheet,
    render_sheet_docx,
    render_sheet_html,
    sheet_file_name,
    validate_exam_sheet_spec,
    whitespace_px_for,
)
from services.models import (
    AnimatedExplanationSpec,
    ExamSheet,
    ExamSheetResult,
    KCMastery,
    KnowledgeCluster,
    KnowledgeUnit,
    QuestionRecord,
    Textbook,
    User,
    UserRole,
    WrongQuestion,
)

TB_ID = "wnb-test-textbook"
CLUSTER_ID = "wnb-test-cluster"
KU_ID = "wnb-test-ku"

Q1_STEM = "下列哪个是一次函数？ A. y=x  B. y=x^2  C. y=1/x  D. y=|x|"
Q2_STEM = "解方程组：\n（1）x+y=5\n（2）x-y=1"


# ── 纯函数：组卷拼装 ──────────────────────────────────────────────────────


def _sheet_spec(items, **overrides):
    spec = {
        "id": "sheet-wnb-1",
        "title": "错题组卷·测试",
        "items": items,
        "include_answer_page": True,
    }
    spec.update(overrides)
    return spec


def _owned(qid, stem, answer):
    return {
        "id": qid,
        "subject": "math",
        "question_text": stem,
        "correct_answer": answer,
    }


def test_assemble_happy_path_with_answer_page():
    q1 = str(uuid.uuid4())
    q2 = str(uuid.uuid4())
    spec = _sheet_spec(
        [
            {"wrong_question_id": q1},
            {"wrong_question_id": q2, "whitespace_px": 100},
        ]
    )
    owned = [
        _owned(q1, Q1_STEM, "A"),
        _owned(q2, Q2_STEM, None),
    ]
    stats = {q1: {"attempts": 2, "last_is_correct": True, "last_answered_at": "2026-11-02T00:00:00+00:00"}}
    assembled, issues = assemble_exam_sheet(spec, owned, stats)
    assert issues == [], [vars(i) for i in issues]
    assert assembled is not None
    assert len(assembled["questions"]) == 2
    first, second = assembled["questions"]
    assert first["whitespace_px"] == 48  # 选择题 auto
    assert first["attempts"] == 2
    assert first["last_is_correct"] is True
    assert second["whitespace_px"] == 100  # 单题 override 优先
    assert second["attempts"] == 0
    assert [a["number"] for a in assembled["answer_key"]] == [1]
    assert assembled["unanswered"] == [2]  # 无答案的题答案页留空并标注


def test_assemble_rejects_unowned_and_missing():
    q1 = str(uuid.uuid4())
    ghost = str(uuid.uuid4())
    spec = _sheet_spec([{"wrong_question_id": q1}, {"wrong_question_id": ghost}])
    assembled, issues = assemble_exam_sheet(spec, [_owned(q1, Q1_STEM, "A")])
    assert assembled is None
    assert any(i.code == "question_not_owned" for i in issues)


def test_assemble_whitespace_override_out_of_range():
    q1 = str(uuid.uuid4())
    spec = _sheet_spec([{"wrong_question_id": q1, "whitespace_px": 481}])
    issues = validate_exam_sheet_spec(spec)
    assert any(i.code == "whitespace_out_of_range" for i in issues)
    spec = _sheet_spec([{"wrong_question_id": q1, "whitespace_px": 0}])
    assert validate_exam_sheet_spec(spec) == []


def test_assemble_duplicate_item_and_too_many():
    q1 = str(uuid.uuid4())
    spec = _sheet_spec([{"wrong_question_id": q1}, {"wrong_question_id": q1}])
    assert any(i.code == "duplicate_question" for i in validate_exam_sheet_spec(spec))
    spec = _sheet_spec([{"wrong_question_id": str(uuid.uuid4())} for _ in range(51)])
    assert any(i.code == "too_many_items" for i in validate_exam_sheet_spec(spec))


def test_assemble_bad_figure_key():
    q1 = str(uuid.uuid4())
    spec = _sheet_spec(
        [{"wrong_question_id": q1, "figure_key": "https://example.com/x.png"}]
    )
    assert any(i.code == "bad_figure_key" for i in validate_exam_sheet_spec(spec))
    spec = _sheet_spec(
        [{"wrong_question_id": q1, "figure_key": "figures/doc1/p3_0.png"}]
    )
    assert validate_exam_sheet_spec(spec) == []


def test_whitespace_auto_by_kind():
    assert whitespace_px_for("auto", Q1_STEM) == 48
    assert whitespace_px_for("auto", "判断下列说法是否正确：一次函数的图像是一条直线。") == 40
    assert whitespace_px_for("auto", "一次函数 y=2x+1 的图像与 y 轴交于点（____，____）。") == 72
    assert whitespace_px_for("auto", Q2_STEM) == 280  # 解答题 2 小问
    assert whitespace_px_for("auto", "求 x+1=0 的解。") == 200
    assert whitespace_px_for("large", Q1_STEM) == 256
    assert whitespace_px_for("none", Q1_STEM, override=0) == 0


def test_render_html_contains_stems_and_spaces():
    q1 = str(uuid.uuid4())
    q2 = str(uuid.uuid4())
    spec = _sheet_spec([{"wrong_question_id": q1}, {"wrong_question_id": q2}])
    assembled, issues = assemble_exam_sheet(
        spec,
        [_owned(q1, Q1_STEM, "A"), _owned(q2, Q2_STEM, None)],
    )
    assert issues == []
    html_text = render_sheet_html(assembled)
    assert Q1_STEM in html_text
    assert "x+y=5" in html_text
    assert "min-height:48px" in html_text
    assert "min-height:280px" in html_text
    assert "答案页" in html_text
    assert "A</p>" in html_text
    assert "未收录答案" in html_text
    assert "http" not in html_text  # 自包含，无外部资源


def test_render_docx_zip_and_xml():
    q1 = str(uuid.uuid4())
    q2 = str(uuid.uuid4())
    spec = _sheet_spec([{"wrong_question_id": q1}, {"wrong_question_id": q2}])
    assembled, issues = assemble_exam_sheet(
        spec,
        [_owned(q1, Q1_STEM, "A"), _owned(q2, Q2_STEM, None)],
    )
    assert issues == []
    blob = render_sheet_docx(assembled)
    zf = zipfile.ZipFile(io.BytesIO(blob))
    assert zf.testzip() is None
    assert zf.namelist() == [
        "[Content_Types].xml",
        "_rels/.rels",
        "word/document.xml",
        "word/styles.xml",
    ]
    root = ET.fromstring(zf.read("word/document.xml"))
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    texts = [t.text or "" for t in root.iterfind(".//w:t", ns)]
    joined = "\n".join(texts)
    assert Q1_STEM in joined
    assert "x+y=5" in joined
    assert "答案页" in joined


def test_sheet_file_name_sanitizes():
    assert sheet_file_name("错题组卷/第一期：函数?", "html") == "错题组卷_第一期：函数.html"
    assert sheet_file_name("   ", "docx") == "exam-sheet.docx"


# ── 纯函数：动画讲解 ──────────────────────────────────────────────────────


def _codes(result):
    return [i.code for i in result.issues]


def test_linear_animation_passes_and_assembles():
    spec = _anim_spec(ku_id=KU_ID)
    result = verify_animation(
        spec, known_ku_ids={KU_ID}, known_question_ids=set()
    )
    assert result.passed, [vars(i) for i in result.issues]
    animation = assemble_animation(spec)
    assert len(animation["steps"]) == 3
    begins = [s["begin_ms"] for s in animation["steps"]]
    assert begins[0] == 0
    assert begins[1] == animation["steps"][0]["min_duration_ms"]
    assert begins[2] == begins[1] + animation["steps"][1]["min_duration_ms"]
    for step in animation["steps"]:
        assert step["narration"]["zh"]
        assert step["narration"]["en"]
        assert step["frames"]
    assert animation["provenance"]["label"] == "generated"


def test_pythagorean_animation_passes():
    spec = _pyth_spec(ku_id=KU_ID)
    result = verify_animation(
        spec, known_ku_ids={KU_ID}, known_question_ids=set()
    )
    assert result.passed, [vars(i) for i in result.issues]
    animation = assemble_animation(spec)
    assert len(animation["steps"]) == 3
    assert {"sq_a", "sq_b", "sq_c"} <= set(
        animation["steps"][2]["frames"][0]["show"]
    )


def test_animation_rejects_verified_key_and_bad_id():
    spec = _anim_spec(ku_id=KU_ID)
    spec["verified"] = True
    result = verify_animation(spec, known_ku_ids={KU_ID}, known_question_ids=set())
    assert "verified_field_forbidden" in _codes(result)

    spec = _anim_spec(ku_id=KU_ID)
    spec["id"] = ""
    result = verify_animation(spec, known_ku_ids={KU_ID}, known_question_ids=set())
    assert "missing_id" in _codes(result)


def test_animation_rejects_empty_steps_and_narration():
    spec = _anim_spec(ku_id=KU_ID)
    spec["steps"] = []
    result = verify_animation(spec, known_ku_ids={KU_ID}, known_question_ids=set())
    assert "bad_step_count" in _codes(result)

    spec = _anim_spec(ku_id=KU_ID)
    spec["steps"][0]["narration_text"] = {"zh": "", "en": ""}
    result = verify_animation(spec, known_ku_ids={KU_ID}, known_question_ids=set())
    assert "missing_language" in _codes(result)


def test_animation_rejects_undeclared_shape_and_bad_frame():
    spec = _anim_spec(ku_id=KU_ID)
    spec["steps"][0]["scene"]["frames"][0]["show"] = ["no_such_shape"]
    result = verify_animation(spec, known_ku_ids={KU_ID}, known_question_ids=set())
    assert "undeclared_shape" in _codes(result)

    spec = _anim_spec(ku_id=KU_ID)
    spec["steps"][0]["scene"]["frames"][0]["set"] = {"line1": {"color": "red"}}
    result = verify_animation(spec, known_ku_ids={KU_ID}, known_question_ids=set())
    assert "not_settable" in _codes(result)

    spec = _anim_spec(ku_id=KU_ID)
    spec["steps"][0]["scene"]["frames"][0]["duration_ms"] = 50
    result = verify_animation(spec, known_ku_ids={KU_ID}, known_question_ids=set())
    assert "frame_duration_out_of_range" in _codes(result)


def test_animation_duration_bounds():
    spec = _anim_spec(ku_id=KU_ID)
    spec["steps"][0]["min_duration_ms"] = 100
    result = verify_animation(spec, known_ku_ids={KU_ID}, known_question_ids=set())
    assert "step_duration_out_of_range" in _codes(result)

    spec = _anim_spec(ku_id=KU_ID)
    for step in spec["steps"]:
        step["min_duration_ms"] = 60000
    for _ in range(8):
        spec["steps"].append(dict(spec["steps"][0]))
    result = verify_animation(spec, known_ku_ids={KU_ID}, known_question_ids=set())
    assert "total_duration_too_long" in _codes(result)


def test_animation_references_fail_closed():
    qid = str(uuid.uuid4())
    spec = _anim_spec(ku_id=KU_ID, question_id=qid)
    # 核验集 None 时不通过（fail-closed）
    result = verify_animation(spec, known_ku_ids={KU_ID}, known_question_ids=None)
    assert "question_not_found" in _codes(result)
    # 引用不存在时不通过
    result = verify_animation(
        spec, known_ku_ids={KU_ID}, known_question_ids=set()
    )
    assert "question_not_found" in _codes(result)
    # 引用存在时通过
    result = verify_animation(
        spec, known_ku_ids={KU_ID}, known_question_ids={qid}
    )
    assert result.passed, [vars(i) for i in result.issues]

    spec = _anim_spec(ku_id="no-such-ku")
    result = verify_animation(
        spec, known_ku_ids={KU_ID}, known_question_ids=set()
    )
    assert "ku_not_found" in _codes(result)


def test_animation_provenance_labels():
    spec = _anim_spec(ku_id=KU_ID)
    prov = animation_provenance(spec)
    assert prov["label"] == "generated"
    spec["provenance"] = {"label": "material", "sources": []}
    result = verify_animation(spec, known_ku_ids={KU_ID}, known_question_ids=set())
    assert "material_needs_sources" in _codes(result)
    spec["provenance"] = {"label": "bogus", "sources": []}
    result = verify_animation(spec, known_ku_ids={KU_ID}, known_question_ids=set())
    assert "bad_label" in _codes(result)


# ── 迁移 pin 与单头 ────────────────────────────────────────────────────────


def test_migration_pin_matches_single_head():
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from pathlib import Path

    from services.routers.health import EXPECTED_MIGRATION_HEAD

    repo_root = Path(__file__).resolve().parents[1]
    cfg = Config(str(repo_root / "alembic.ini"))
    script = ScriptDirectory.from_config(cfg)
    assert tuple(script.get_heads()) == ("phy1a2b3c4d5e",)
    assert EXPECTED_MIGRATION_HEAD == "phy1a2b3c4d5e"
    assert script.get_revision("wnb1a2b3c4d5e").down_revision == "all1a2b3c4d5e"
    assert script.get_revision("phy1a2b3c4d5e").down_revision == "wnb1a2b3c4d5e"


@pytest.mark.asyncio
async def test_migration_upgrades_to_single_head():
    """迁移 upgrade/downgrade 真跑（克隆库，跑完即删）。模式同 teachfig 测试。

    共享 mneme_test 的版本行漂移在他分支 revision，且全链空库 upgrade
    在既有 word-atlas 迁移处已断——均为本迁移之外的既有状态，不越界修。
    故克隆 mneme_test 为一次性库，删固件自建表后 stamp 父 revision，
    只跑本迁移 upgrade head 与 downgrade 回父 revision；绝不碰生产库。
    """
    import os
    import subprocess
    import sys
    from pathlib import Path

    import asyncpg
    from sqlalchemy.engine.url import make_url

    base_url = os.environ["DATABASE_URL"]
    url = make_url(base_url)
    assert url.database == "mneme_test", "迁移测试只许以 mneme_test 为基"
    scratch = "mneme_test_wnb"
    dsn = (
        f"postgresql://{url.username}:{url.password}"
        f"@{url.host}:{url.port}/postgres"
    )
    repo_root = Path(__file__).resolve().parents[1]

    def _alembic(*args):
        env = dict(os.environ)
        env["DATABASE_URL"] = url.set(database=scratch).render_as_string(hide_password=False)
        env["PYTHONPATH"] = str(repo_root)
        proc = subprocess.run(
            [sys.executable, "-m", "alembic", *args],
            cwd=repo_root, env=env, capture_output=True, text=True, timeout=180,
        )
        assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]

    maint = await asyncpg.connect(dsn)
    try:
        await maint.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = 'mneme_test' AND pid <> pg_backend_pid()"
        )
        await maint.execute(f'DROP DATABASE IF EXISTS "{scratch}"')
        await maint.execute(
            f'CREATE DATABASE "{scratch}" TEMPLATE "mneme_test"'
        )
    finally:
        await maint.close()
    try:
        conn = await asyncpg.connect(dsn.rsplit("/", 1)[0] + f"/{scratch}")
        try:
            await conn.execute("DROP TABLE IF EXISTS exam_sheet_results CASCADE")
            await conn.execute("DROP TABLE IF EXISTS exam_sheets CASCADE")
            await conn.execute(
                "DROP TABLE IF EXISTS animated_explanation_specs CASCADE"
            )
            await conn.execute("DROP TABLE IF EXISTS physics_models CASCADE")
            await conn.execute("DROP TABLE IF EXISTS physics_practice_items CASCADE")
            await conn.execute("DELETE FROM alembic_version")
            await conn.execute(
                "INSERT INTO alembic_version VALUES ('all1a2b3c4d5e')"
            )
        finally:
            await conn.close()
        _alembic("upgrade", "head")
        conn = await asyncpg.connect(dsn.rsplit("/", 1)[0] + f"/{scratch}")
        try:
            version = await conn.fetchval(
                "SELECT version_num FROM alembic_version"
            )
            tables = {
                name: await conn.fetchval(
                    "SELECT to_regclass('public." + name + "')"
                )
                for name in (
                    "exam_sheets",
                    "exam_sheet_results",
                    "animated_explanation_specs",
                )
            }
            indexes = {
                name: await conn.fetchval(
                    "SELECT indexname FROM pg_indexes WHERE indexname = $1", name
                )
                for name in (
                    "ix_exam_sheets_student_id",
                    "ix_exam_sheet_results_sheet_id",
                    "ix_animated_explanation_specs_ku_id",
                    "ix_animated_explanation_specs_question_id",
                )
            }
        finally:
            await conn.close()
        assert version == "phy1a2b3c4d5e"
        assert tables == {
            "exam_sheets": "exam_sheets",
            "exam_sheet_results": "exam_sheet_results",
            "animated_explanation_specs": "animated_explanation_specs",
        }
        assert all(indexes.values()), indexes
        _alembic("downgrade", "all1a2b3c4d5e")
        conn = await asyncpg.connect(dsn.rsplit("/", 1)[0] + f"/{scratch}")
        try:
            version = await conn.fetchval(
                "SELECT version_num FROM alembic_version"
            )
            gone = await conn.fetchval(
                "SELECT to_regclass('public.exam_sheets')"
            )
        finally:
            await conn.close()
        assert version == "all1a2b3c4d5e"
        assert gone is None
    finally:
        maint = await asyncpg.connect(dsn)
        try:
            await maint.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                f"WHERE datname = '{scratch}'"
            )
            await maint.execute(f'DROP DATABASE IF EXISTS "{scratch}"')
        finally:
            await maint.close()


# ── 路由（库上） ───────────────────────────────────────────────────────────


@pytest.fixture(scope="session", autouse=True)
async def _ensure_wnb_tables():
    """mneme_test 尚未应用本迁移（版本行漂移在他分支 revision），固件按
    迁移同源 DDL 自建表（IF NOT EXISTS），仅测试库；生产部署仍以
    alembic upgrade head 为准，见 test_migration_upgrades_to_single_head。"""
    import os

    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(os.environ["DATABASE_URL"])
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS exam_sheets ("
                "id VARCHAR(100) NOT NULL, "
                "student_id UUID NOT NULL REFERENCES users(id), "
                "spec JSONB NOT NULL, "
                "created_at TIMESTAMPTZ NOT NULL DEFAULT now(), "
                "updated_at TIMESTAMPTZ NOT NULL DEFAULT now(), "
                "PRIMARY KEY (id))"
            )
        )
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_exam_sheets_student_id "
                "ON exam_sheets (student_id)"
            )
        )
        await conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS exam_sheet_results ("
                "id UUID NOT NULL DEFAULT gen_random_uuid(), "
                "sheet_id VARCHAR(100) NOT NULL REFERENCES exam_sheets(id), "
                "wrong_question_id UUID NOT NULL, "
                "is_correct BOOLEAN NOT NULL, "
                "seconds INTEGER, "
                "answered_at TIMESTAMPTZ NOT NULL DEFAULT now(), "
                "PRIMARY KEY (id), "
                "CONSTRAINT uq_exam_sheet_results_sheet_question "
                "UNIQUE (sheet_id, wrong_question_id))"
            )
        )
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_exam_sheet_results_sheet_id "
                "ON exam_sheet_results (sheet_id)"
            )
        )
        await conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS animated_explanation_specs ("
                "id VARCHAR(100) NOT NULL, "
                "question_id VARCHAR(128), "
                "ku_id VARCHAR(100), "
                "spec JSONB NOT NULL, "
                "verified BOOLEAN NOT NULL DEFAULT false, "
                "author_id UUID NOT NULL REFERENCES users(id), "
                "created_at TIMESTAMPTZ NOT NULL DEFAULT now(), "
                "updated_at TIMESTAMPTZ NOT NULL DEFAULT now(), "
                "PRIMARY KEY (id))"
            )
        )
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_animated_explanation_specs_ku_id "
                "ON animated_explanation_specs (ku_id)"
            )
        )
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS "
                "ix_animated_explanation_specs_question_id "
                "ON animated_explanation_specs (question_id)"
            )
        )
    await engine.dispose()
    yield


@pytest.fixture
async def _seed():
    """种入教材 + cluster + KU + 两名学生 + 三道错题；teardown 只清自己种的 id。"""
    from obase.db import SessionLocal

    owner_id = uuid.uuid4()
    other_id = uuid.uuid4()
    q1 = uuid.uuid4()
    q2 = uuid.uuid4()
    q3 = uuid.uuid4()
    async with SessionLocal() as db:
        if (await db.get(Textbook, TB_ID)) is None:
            db.add(Textbook(id=TB_ID, subject="math", grade="初二",
                            edition="2017修订", book_name="测试教材"))
            await db.flush()
        if (await db.get(KnowledgeCluster, CLUSTER_ID)) is None:
            db.add(KnowledgeCluster(id=CLUSTER_ID, textbook_id=TB_ID,
                                    name="测试簇", display_order=1))
            await db.flush()
        if (await db.get(KnowledgeUnit, KU_ID)) is None:
            db.add(KnowledgeUnit(id=KU_ID, textbook_id=TB_ID, cluster_id=CLUSTER_ID,
                                 name="测试知识点", description="夹具",
                                 difficulty=0.5, exam_frequency="mid",
                                 ku_type="concept", verified=False))
        for uid in (owner_id, other_id):
            db.add(User(id=uid, phone=f"150{str(uuid.uuid4())[:8]}",
                        role=UserRole.student))
        db.add(WrongQuestion(id=q1, student_id=owner_id, subject="math",
                             question_text=Q1_STEM, correct_answer="A"))
        db.add(WrongQuestion(id=q2, student_id=owner_id, subject="math",
                             question_text=Q2_STEM, correct_answer=None))
        db.add(WrongQuestion(id=q3, student_id=other_id, subject="math",
                             question_text="他人的错题", correct_answer="B"))
        await db.commit()
    yield {"owner": owner_id, "other": other_id, "q1": q1, "q2": q2, "q3": q3}
    async with SessionLocal() as db:
        await db.execute(
            delete(ExamSheetResult).where(
                ExamSheetResult.sheet_id.in_(
                    select(ExamSheet.id).where(
                        ExamSheet.student_id.in_([owner_id, other_id])
                    )
                )
            )
        )
        await db.execute(
            delete(ExamSheet).where(
                ExamSheet.student_id.in_([owner_id, other_id])
            )
        )
        await db.execute(
            delete(AnimatedExplanationSpec).where(
                AnimatedExplanationSpec.author_id.in_([owner_id, other_id])
            )
        )
        await db.execute(
            delete(QuestionRecord).where(
                QuestionRecord.student_id.in_([owner_id, other_id]),
                QuestionRecord.source == "exam_sheet",
            )
        )
        await db.execute(
            delete(WrongQuestion).where(
                WrongQuestion.id.in_([q1, q2, q3])
            )
        )
        await db.execute(
            delete(KCMastery).where(KCMastery.student_id.in_([owner_id, other_id]))
        )
        await db.execute(delete(KnowledgeUnit).where(KnowledgeUnit.id == KU_ID))
        await db.execute(
            delete(KnowledgeCluster).where(KnowledgeCluster.id == CLUSTER_ID)
        )
        await db.execute(delete(Textbook).where(Textbook.id == TB_ID))
        await db.execute(
            delete(User).where(User.id.in_([owner_id, other_id]))
        )
        await db.commit()


@pytest.fixture
async def _client():
    from services.main import app

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client


def _as_anim_admin(monkeypatch, admin=True):
    monkeypatch.setattr(
        "services.routers.animated_explanations.is_admin", lambda u: admin
    )


def _anim_spec(spec_id="anim-wnb-1", **overrides):
    spec = linear_shift_spec(spec_id=spec_id)
    spec.update(overrides)
    return spec


def _pyth_spec(spec_id="anim-wnb-2", **overrides):
    spec = pythagorean_spec(spec_id=spec_id)
    spec.update(overrides)
    return spec


@pytest.mark.asyncio
async def test_exam_sheet_create_get_list(_client, _seed, bypass_auth):
    owner = str(_seed["owner"])
    payload = {
        "spec": _sheet_spec(
            [
                {"wrong_question_id": str(_seed["q1"])},
                {"wrong_question_id": str(_seed["q2"])},
            ]
        ),
        "student_id": owner,
    }
    resp = await _client.post("/v1/exam-sheets", json=payload)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == "sheet-wnb-1"
    assert body["student_id"] == owner
    assert len(body["spec"]["questions"]) == 2
    assert body["spec"]["questions"][0]["attempts"] == 0

    resp = await _client.get(
        "/v1/exam-sheets/sheet-wnb-1", params={"student_id": owner}
    )
    assert resp.status_code == 200
    # 他人不可见（404，不泄露存在性）
    resp = await _client.get(
        "/v1/exam-sheets/sheet-wnb-1", params={"student_id": str(_seed["other"])}
    )
    assert resp.status_code == 404

    resp = await _client.get("/v1/exam-sheets", params={"student_id": owner})
    assert resp.status_code == 200
    assert [i["id"] for i in resp.json()["items"]] == ["sheet-wnb-1"]


@pytest.mark.asyncio
async def test_exam_sheet_list_requires_auth(_client, _seed):
    resp = await _client.get(
        "/v1/exam-sheets", params={"student_id": str(_seed["owner"])}
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_exam_sheet_create_rejects_foreign_question(_client, _seed, bypass_auth):
    owner = str(_seed["owner"])
    payload = {
        "spec": _sheet_spec([{"wrong_question_id": str(_seed["q3"])}]),
        "student_id": owner,
    }
    resp = await _client.post("/v1/exam-sheets", json=payload)
    assert resp.status_code == 422
    assert "question_not_owned" in str(resp.json())

    payload = {
        "spec": _sheet_spec([{"wrong_question_id": str(uuid.uuid4())}]),
        "student_id": owner,
    }
    resp = await _client.post("/v1/exam-sheets", json=payload)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_exam_sheet_create_duplicate_id_409(_client, _seed, bypass_auth):
    owner = str(_seed["owner"])
    payload = {
        "spec": _sheet_spec([{"wrong_question_id": str(_seed["q1"])}]),
        "student_id": owner,
    }
    assert (await _client.post("/v1/exam-sheets", json=payload)).status_code == 200
    resp = await _client.post("/v1/exam-sheets", json=payload)
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_exam_sheet_export_html_and_docx(_client, _seed, bypass_auth):
    owner = str(_seed["owner"])
    payload = {
        "spec": _sheet_spec(
            [
                {"wrong_question_id": str(_seed["q1"])},
                {"wrong_question_id": str(_seed["q2"])},
            ]
        ),
        "student_id": owner,
    }
    assert (await _client.post("/v1/exam-sheets", json=payload)).status_code == 200

    resp = await _client.get(
        "/v1/exam-sheets/sheet-wnb-1/export",
        params={"format": "html", "student_id": owner},
    )
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/html")
    assert "attachment" in resp.headers["content-disposition"]
    assert Q1_STEM in resp.text
    assert "x+y=5" in resp.text

    resp = await _client.get(
        "/v1/exam-sheets/sheet-wnb-1/export",
        params={"format": "docx", "student_id": owner},
    )
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    zf = zipfile.ZipFile(io.BytesIO(resp.content))
    assert zf.testzip() is None
    root = ET.fromstring(zf.read("word/document.xml"))
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    joined = "\n".join(t.text or "" for t in root.iterfind(".//w:t", ns))
    assert Q1_STEM in joined
    assert "x+y=5" in joined

    resp = await _client.get(
        "/v1/exam-sheets/sheet-wnb-1/export",
        params={"format": "pdf", "student_id": owner},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_exam_sheet_results_flow(_client, _seed, bypass_auth):
    from obase.db import SessionLocal

    owner = _seed["owner"]
    payload = {
        "spec": _sheet_spec(
            [
                {"wrong_question_id": str(_seed["q1"])},
                {"wrong_question_id": str(_seed["q2"])},
            ]
        ),
        "student_id": str(owner),
    }
    assert (await _client.post("/v1/exam-sheets", json=payload)).status_code == 200

    resp = await _client.post(
        "/v1/exam-sheets/sheet-wnb-1/results",
        params={"student_id": str(owner)},
        json={
            "results": [
                {
                    "wrong_question_id": str(_seed["q1"]),
                    "is_correct": True,
                    "seconds": 45,
                },
                {"wrong_question_id": str(_seed["q2"]), "is_correct": False},
            ]
        },
    )
    assert resp.status_code == 200, resp.text
    assert len(resp.json()["recorded"]) == 2

    async with SessionLocal() as db:
        records = (
            await db.execute(
                select(QuestionRecord).where(
                    QuestionRecord.student_id == owner,
                    QuestionRecord.source == "exam_sheet",
                )
            )
        ).scalars().all()
        assert len(records) == 2
        by_q = {str(r.wrong_question_id): r for r in records}
        assert by_q[str(_seed["q1"])].grader == "sheet"
        assert by_q[str(_seed["q1"])].duration_ms == 45000
        assert by_q[str(_seed["q1"])].meta == {
            "solution": "exam_sheet",
            "sheet_id": "sheet-wnb-1",
        }
        results = (
            await db.execute(
                select(ExamSheetResult).where(
                    ExamSheetResult.sheet_id == "sheet-wnb-1"
                )
            )
        ).scalars().all()
        assert len(results) == 2
        # FSRS 排期跑了（卡片落库），但 BKT 掌握度一字未写
        wq = await db.get(WrongQuestion, _seed["q1"])
        assert wq.fsrs_card_json is not None
        assert wq.fsrs_due is not None
        mastery = (
            await db.execute(
                select(KCMastery).where(KCMastery.student_id == owner)
            )
        ).scalars().all()
        assert mastery == []

    # 统计随回填更新：组卷详情带 attempt 计数与最近结果
    resp = await _client.get(
        "/v1/exam-sheets/sheet-wnb-1", params={"student_id": str(owner)}
    )
    assert resp.status_code == 200
    questions = {q["wrong_question_id"]: q for q in resp.json()["spec"]["questions"]}
    assert questions[str(_seed["q1"])]["attempts"] == 1
    assert questions[str(_seed["q1"])]["last_is_correct"] is True
    assert questions[str(_seed["q2"])]["last_is_correct"] is False

    # 重复提交同一题 → 409，且不追加新记录
    resp = await _client.post(
        "/v1/exam-sheets/sheet-wnb-1/results",
        params={"student_id": str(owner)},
        json={
            "results": [
                {"wrong_question_id": str(_seed["q1"]), "is_correct": True}
            ]
        },
    )
    assert resp.status_code == 409
    async with SessionLocal() as db:
        count = (
            await db.execute(
                select(QuestionRecord).where(
                    QuestionRecord.student_id == owner,
                    QuestionRecord.source == "exam_sheet",
                )
            )
        ).scalars().all()
        assert len(count) == 2


@pytest.mark.asyncio
async def test_exam_sheet_results_rejects_bad_payload(_client, _seed, bypass_auth):
    owner = str(_seed["owner"])
    payload = {
        "spec": _sheet_spec([{"wrong_question_id": str(_seed["q1"])}]),
        "student_id": owner,
    }
    assert (await _client.post("/v1/exam-sheets", json=payload)).status_code == 200

    # 不在本卷的题
    resp = await _client.post(
        "/v1/exam-sheets/sheet-wnb-1/results",
        params={"student_id": owner},
        json={
            "results": [
                {"wrong_question_id": str(_seed["q2"]), "is_correct": True}
            ]
        },
    )
    assert resp.status_code == 422
    assert "question_not_in_sheet" in str(resp.json())
    # is_correct 非布尔
    resp = await _client.post(
        "/v1/exam-sheets/sheet-wnb-1/results",
        params={"student_id": owner},
        json={
            "results": [
                {"wrong_question_id": str(_seed["q1"]), "is_correct": "yes"}
            ]
        },
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_animation_create_requires_admin(_client, _seed, bypass_auth, monkeypatch):
    _as_anim_admin(monkeypatch, False)
    resp = await _client.post(
        "/v1/animated-explanations",
        json={"spec": _anim_spec(), "student_id": str(_seed["owner"])},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_animation_create_verify_assemble_flow(
    _client, _seed, bypass_auth, monkeypatch
):
    owner = str(_seed["owner"])
    _as_anim_admin(monkeypatch, True)
    resp = await _client.post(
        "/v1/animated-explanations",
        json={"spec": _anim_spec(), "student_id": owner},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["verified"] is False
    assert resp.json()["provenance"]["label"] == "generated"

    # 学生看不到未验证的规格
    _as_anim_admin(monkeypatch, False)
    resp = await _client.get(
        "/v1/animated-explanations/anim-wnb-1", params={"student_id": owner}
    )
    assert resp.status_code == 404
    resp = await _client.get(
        "/v1/animated-explanations/anim-wnb-1/assemble",
        params={"student_id": owner},
    )
    assert resp.status_code == 404

    # admin verify 后学生可见 + 可拼装
    _as_anim_admin(monkeypatch, True)
    resp = await _client.post(
        "/v1/animated-explanations/anim-wnb-1/verify",
        params={"student_id": owner},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["verified"] is True
    _as_anim_admin(monkeypatch, False)
    resp = await _client.get(
        "/v1/animated-explanations/anim-wnb-1", params={"student_id": owner}
    )
    assert resp.status_code == 200
    resp = await _client.get(
        "/v1/animated-explanations/anim-wnb-1/assemble",
        params={"student_id": owner},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["animation"]["steps"]) == 3
    assert body["animation"]["steps"][0]["begin_ms"] == 0
    assert body["animation"]["provenance"]["label"] == "generated"


@pytest.mark.asyncio
async def test_animation_create_invalid_and_duplicate(
    _client, _seed, bypass_auth, monkeypatch
):
    owner = str(_seed["owner"])
    _as_anim_admin(monkeypatch, True)
    spec = _anim_spec()
    spec["verified"] = True
    resp = await _client.post(
        "/v1/animated-explanations",
        json={"spec": spec, "student_id": owner},
    )
    assert resp.status_code == 422
    assert "verified_field_forbidden" in str(resp.json())

    spec = _anim_spec()
    spec["ku_id"] = "no-such-ku"
    resp = await _client.post(
        "/v1/animated-explanations",
        json={"spec": spec, "student_id": owner},
    )
    assert resp.status_code == 422
    assert "ku_not_found" in str(resp.json())

    payload = {"spec": _anim_spec(), "student_id": owner}
    assert (await _client.post("/v1/animated-explanations", json=payload)).status_code == 200
    resp = await _client.post("/v1/animated-explanations", json=payload)
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_animation_verify_requires_admin_and_rejects(
    _client, _seed, bypass_auth, monkeypatch
):
    from obase.db import SessionLocal

    owner = str(_seed["owner"])
    _as_anim_admin(monkeypatch, True)
    payload = {"spec": _anim_spec(), "student_id": owner}
    assert (await _client.post("/v1/animated-explanations", json=payload)).status_code == 200
    _as_anim_admin(monkeypatch, False)
    resp = await _client.post(
        "/v1/animated-explanations/anim-wnb-1/verify",
        params={"student_id": owner},
    )
    assert resp.status_code == 403

    # 门禁不过的规格 verify 失败且保持未验证
    _as_anim_admin(monkeypatch, True)
    broken = _anim_spec(spec_id="anim-wnb-broken", ku_id="no-such-ku")
    async with SessionLocal() as db:
        db.add(
            AnimatedExplanationSpec(
                id="anim-wnb-broken",
                ku_id="no-such-ku",
                spec=broken,
                verified=False,
                author_id=_seed["owner"],
            )
        )
        await db.commit()
    resp = await _client.post(
        "/v1/animated-explanations/anim-wnb-broken/verify",
        params={"student_id": owner},
    )
    assert resp.status_code == 422
    assert "ku_not_found" in str(resp.json())
    async with SessionLocal() as db:
        row = await db.get(AnimatedExplanationSpec, "anim-wnb-broken")
        assert row is not None and row.verified is False
        await db.delete(row)
        await db.commit()


@pytest.mark.asyncio
async def test_animation_list_filters(_client, _seed, bypass_auth, monkeypatch):
    owner = str(_seed["owner"])
    _as_anim_admin(monkeypatch, True)
    assert (
        await _client.post(
            "/v1/animated-explanations",
            json={"spec": _anim_spec(), "student_id": owner},
        )
    ).status_code == 200
    assert (
        await _client.post(
            "/v1/animated-explanations",
            json={
                "spec": _pyth_spec(ku_id=KU_ID),
                "student_id": owner,
            },
        )
    ).status_code == 200
    await _client.post(
        "/v1/animated-explanations/anim-wnb-1/verify",
        params={"student_id": owner},
    )
    _as_anim_admin(monkeypatch, False)
    resp = await _client.get(
        "/v1/animated-explanations", params={"student_id": owner}
    )
    assert [i["id"] for i in resp.json()["items"]] == ["anim-wnb-1"]
    # 学生带 include_unverified 也不见未验证的
    resp = await _client.get(
        "/v1/animated-explanations",
        params={"student_id": owner, "include_unverified": "true"},
    )
    assert [i["id"] for i in resp.json()["items"]] == ["anim-wnb-1"]
    # ku 过滤：不存在的 ku → 空
    resp = await _client.get(
        "/v1/animated-explanations",
        params={"student_id": owner, "ku_id": "no-such-ku"},
    )
    assert resp.json()["items"] == []


@pytest.mark.asyncio
async def test_mcp_get_exam_sheet_and_animation(
    _client, _seed, bypass_auth, monkeypatch
):
    owner = str(_seed["owner"])
    payload = {
        "spec": _sheet_spec([{"wrong_question_id": str(_seed["q1"])}]),
        "student_id": owner,
    }
    assert (await _client.post("/v1/exam-sheets", json=payload)).status_code == 200

    resp = await _client.post(
        "/mcp/GetExamSheet",
        json={"student_id": owner, "sheet_id": "sheet-wnb-1"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["found"] is True
    assert body["sheet"]["spec"]["questions"][0]["attempts"] == 0
    # 他人查同一组卷 → 不泄露
    resp = await _client.post(
        "/mcp/GetExamSheet",
        json={"student_id": str(_seed["other"]), "sheet_id": "sheet-wnb-1"},
    )
    assert resp.json() == {"found": False}

    # 动画：未验证 → 不泄露；验证后 → 拼装结果
    _as_anim_admin(monkeypatch, True)
    assert (
        await _client.post(
            "/v1/animated-explanations",
            json={"spec": _anim_spec(), "student_id": owner},
        )
    ).status_code == 200
    resp = await _client.post(
        "/mcp/GetAnimatedExplanation",
        json={"student_id": owner, "spec_id": "anim-wnb-1"},
    )
    assert resp.json() == {"found": False}
    assert (
        await _client.post(
            "/v1/animated-explanations/anim-wnb-1/verify",
            params={"student_id": owner},
        )
    ).status_code == 200
    resp = await _client.post(
        "/mcp/GetAnimatedExplanation",
        json={"student_id": owner, "spec_id": "anim-wnb-1"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["found"] is True
    assert len(body["animation"]["steps"]) == 3
