"""9 项全嫁接：路由测试（库上，只连 mneme_test）。

固件模式照搬 tests/test_teaching_figure_spec.py：session 级 DDL 自建表
（IF NOT EXISTS，仅测试库）＋ _seed（教材/簇/KU/学生/错题/泛读段）＋
bypass_auth（student_id 经 query/JSON body 解析）＋ _as_admin（按路由
模块 monkeypatch is_admin）。生产部署仍以 alembic upgrade head 为准。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from services.models import (
    DictationAttempt,
    KnowledgeCluster,
    KnowledgeUnit,
    MockExamAttempt,
    QuestionRecord,
    ShadowingAttempt,
    ReadingPassage,
    StudyTask,
    Textbook,
    User,
    UserRole,
    WrongQuestion,
)

KU_ID = "ag-test-ku"
TB_ID = "ag-test-textbook"
CLUSTER_ID = "ag-test-cluster"
PASSAGE_ID = "ag-passage-1"


def _bi(zh, en):
    return {"zh": zh, "en": en}


def _video_spec(spec_id="vl-ag-1", ku_id=KU_ID):
    from services.video_lesson import triangle_angle_sum_spec

    spec = triangle_angle_sum_spec(spec_id)
    spec["ku_id"] = ku_id
    return spec


def _dictation_spec(spec_id="dic-ag-1"):
    return {
        "id": spec_id,
        "title": _bi("听写练习", "Dictation practice"),
        "language": "en",
        "level": 1,
        "segments": [
            {"index": 0, "text": "Hello world."},
            {"index": 1, "text": "Good morning."},
        ],
        "source": {"kind": "self_written"},
    }


def _shadowing_spec(spec_id="sh-ag-1"):
    return {
        "id": spec_id,
        "title": _bi("跟读练习", "Shadowing practice"),
        "language": "en",
        "level": 1,
        "target_sentences": ["Hello world.", "Good morning."],
    }


def _graded_spec(spec_id="ga-ag-1"):
    return {
        "id": spec_id,
        "title": _bi("分级有声", "Graded audio"),
        "language": "en",
        "level": 1,
        "text": "Hello world. Good morning.",
        "source": {"kind": "self_written"},
    }


def _mock_spec(spec_id, q1, q2):
    return {
        "id": spec_id,
        "title": _bi("模考", "Mock exam"),
        "subject": "math",
        "level": 1,
        "sections": [
            {
                "name": _bi("第一部分", "Section one"),
                "seconds": 60,
                "question_ids": [str(q1), str(q2)],
            }
        ],
        "total_seconds": 60,
    }


@pytest.fixture(scope="session", autouse=True)
async def _ensure_ag_tables():
    """mneme_test 尚未应用本迁移，固件按迁移同源 DDL 自建 9 张表。"""
    import os

    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(os.environ["DATABASE_URL"])
    spec_ddl = (
        "id VARCHAR(100) NOT NULL, "
        "spec JSONB NOT NULL, "
        "verified BOOLEAN NOT NULL DEFAULT false, "
        "author_id UUID NOT NULL REFERENCES users(id), "
        "created_at TIMESTAMPTZ NOT NULL DEFAULT now(), "
        "updated_at TIMESTAMPTZ NOT NULL DEFAULT now(), "
        "PRIMARY KEY (id)"
    )
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS video_lesson_specs ("
                "id VARCHAR(100) NOT NULL, "
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
                "CREATE INDEX IF NOT EXISTS ix_video_lesson_specs_ku_id "
                "ON video_lesson_specs (ku_id)"
            )
        )
        for table in (
            "dictation_specs",
            "shadowing_specs",
            "graded_audio_specs",
            "mock_exam_specs",
        ):
            await conn.execute(
                text(f"CREATE TABLE IF NOT EXISTS {table} ({spec_ddl})")
            )
        await conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS dictation_attempts ("
                "id UUID NOT NULL, "
                "student_id UUID NOT NULL REFERENCES users(id), "
                "spec_id VARCHAR(100) NOT NULL, "
                "score DOUBLE PRECISION NOT NULL, "
                "missed_words JSONB, "
                "fsrs_card_json JSONB, "
                "fsrs_due TIMESTAMPTZ, "
                "created_at TIMESTAMPTZ NOT NULL DEFAULT now(), "
                "PRIMARY KEY (id))"
            )
        )
        await conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS shadowing_attempts ("
                "id UUID NOT NULL, "
                "student_id UUID NOT NULL REFERENCES users(id), "
                "spec_id VARCHAR(100) NOT NULL, "
                "sentence_index INTEGER NOT NULL, "
                "scores JSONB NOT NULL, "
                "transcript TEXT, "
                "weak_words JSONB, "
                "created_at TIMESTAMPTZ NOT NULL DEFAULT now(), "
                "PRIMARY KEY (id))"
            )
        )
        await conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS mock_exam_attempts ("
                "id UUID NOT NULL, "
                "student_id UUID NOT NULL REFERENCES users(id), "
                "spec_id VARCHAR(100) NOT NULL, "
                "answers JSONB NOT NULL, "
                "result JSONB NOT NULL, "
                "late BOOLEAN NOT NULL DEFAULT false, "
                "created_at TIMESTAMPTZ NOT NULL DEFAULT now(), "
                "PRIMARY KEY (id))"
            )
        )
        await conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS study_tasks ("
                "id UUID NOT NULL, "
                "student_id UUID NOT NULL REFERENCES users(id), "
                "title VARCHAR(200) NOT NULL, "
                "notes TEXT, "
                "status VARCHAR(20) NOT NULL DEFAULT 'todo', "
                "due_date DATE, "
                "position INTEGER NOT NULL DEFAULT 0, "
                "archived BOOLEAN NOT NULL DEFAULT false, "
                "created_at TIMESTAMPTZ NOT NULL DEFAULT now(), "
                "updated_at TIMESTAMPTZ NOT NULL DEFAULT now(), "
                "PRIMARY KEY (id))"
            )
        )
    await engine.dispose()
    yield


@pytest.fixture
async def _seed():
    """种入教材 + 簇 + KU + 学生 + 2 错题 + 1 泛读段；teardown 只清自己种的。"""
    from obase.db import SessionLocal

    user_id = uuid.uuid4()
    wq1 = uuid.uuid4()
    wq2 = uuid.uuid4()
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
        db.add(User(id=user_id, phone=f"150{str(uuid.uuid4())[:8]}",
                    role=UserRole.student))
        db.add(WrongQuestion(id=wq1, student_id=user_id, question_text="1+1=?",
                             correct_answer="2", subject="math", source="test-seed",
                             fsrs_due=datetime(2026, 11, 2, 9, 0, tzinfo=timezone.utc)))
        db.add(WrongQuestion(id=wq2, student_id=user_id, question_text="2+2=?",
                             correct_answer="4", subject="math", source="test-seed"))
        if (await db.get(ReadingPassage, PASSAGE_ID)) is None:
            db.add(ReadingPassage(id=PASSAGE_ID, subject="english",
                                  title="Test passage",
                                  body_text="Hello world. Good morning.",
                                  source_url="https://example.com/test",
                                  license="CC BY 4.0", word_count=4,
                                  readability_score=90.0, difficulty_band=1))
        await db.commit()
    yield {"user_id": user_id, "wq1": wq1, "wq2": wq2}
    async with SessionLocal() as db:
        from services.models import (
            DictationSpec,
            GradedAudioSpec,
            MockExamSpec,
            ShadowingSpec,
            VideoLessonSpec,
        )

        for _table in (
            VideoLessonSpec,
            DictationSpec,
            ShadowingSpec,
            GradedAudioSpec,
            MockExamSpec,
        ):
            await db.execute(delete(_table))
        await db.execute(delete(QuestionRecord).where(
            QuestionRecord.student_id == user_id))
        await db.execute(delete(DictationAttempt).where(
            DictationAttempt.student_id == user_id))
        await db.execute(delete(MockExamAttempt).where(
            MockExamAttempt.student_id == user_id))
        await db.execute(delete(ShadowingAttempt).where(
            ShadowingAttempt.student_id == user_id))
        await db.execute(delete(StudyTask).where(
            StudyTask.student_id == user_id))
        await db.execute(delete(WrongQuestion).where(
            WrongQuestion.id.in_([wq1, wq2])))
        await db.execute(delete(ReadingPassage).where(
            ReadingPassage.id == PASSAGE_ID))
        await db.execute(delete(KnowledgeUnit).where(KnowledgeUnit.id == KU_ID))
        await db.execute(delete(KnowledgeCluster).where(
            KnowledgeCluster.id == CLUSTER_ID))
        await db.execute(delete(Textbook).where(Textbook.id == TB_ID))
        await db.execute(delete(User).where(User.id == user_id))
        await db.commit()


@pytest.fixture
async def _client():
    from services.main import app

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client


def _as_admin(monkeypatch, module, admin=True):
    monkeypatch.setattr(
        f"services.routers.{module}.is_admin", lambda u: admin
    )


async def _create_spec(_client, _seed, bypass_auth, monkeypatch, module, create_url, spec):
    _as_admin(monkeypatch, module, True)
    resp = await _client.post(
        create_url,
        json={"spec": spec, "student_id": str(_seed["user_id"])},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _verify_spec(_client, _seed, monkeypatch, module, verify_url):
    _as_admin(monkeypatch, module, True)
    resp = await _client.post(
        verify_url,
        params={"student_id": str(_seed["user_id"])},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


# ── 视频课 ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_video_lesson_create_verify_assemble_flow(
    _client, _seed, bypass_auth, monkeypatch
):
    sid = str(_seed["user_id"])
    spec = _video_spec()
    created = await _create_spec(
        _client, _seed, bypass_auth, monkeypatch, "video_lessons",
        "/v1/video-lessons", spec,
    )
    assert created["verified"] is False
    assert created["ku_id"] == KU_ID
    # 学生在验证前看不到：列表空、详情 404。
    _as_admin(monkeypatch, "video_lessons", False)
    resp = await _client.get("/v1/video-lessons", params={"student_id": sid})
    assert resp.status_code == 200
    assert all(item["id"] != "vl-ag-1" for item in resp.json()["items"])
    resp = await _client.get(
        "/v1/video-lessons/vl-ag-1", params={"student_id": sid}
    )
    assert resp.status_code == 404
    # 验证后学生可见、可组装；重复创建 409。
    await _verify_spec(
        _client, _seed, monkeypatch, "video_lessons", "/v1/video-lessons/vl-ag-1/verify"
    )
    _as_admin(monkeypatch, "video_lessons", False)
    resp = await _client.get(
        "/v1/video-lessons/vl-ag-1/assemble", params={"student_id": sid}
    )
    assert resp.status_code == 200, resp.text
    assert len(resp.json()["scenes"]) >= 1
    _as_admin(monkeypatch, "video_lessons", True)
    resp = await _client.post(
        "/v1/video-lessons",
        json={"spec": spec, "student_id": sid},
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_video_lesson_create_requires_admin_and_valid_spec(
    _client, _seed, bypass_auth, monkeypatch
):
    sid = str(_seed["user_id"])
    _as_admin(monkeypatch, "video_lessons", False)
    resp = await _client.post(
        "/v1/video-lessons",
        json={"spec": _video_spec("vl-ag-2"), "student_id": sid},
    )
    assert resp.status_code == 403
    _as_admin(monkeypatch, "video_lessons", True)
    bad = _video_spec("vl-ag-3")
    bad["verified"] = True
    resp = await _client.post(
        "/v1/video-lessons",
        json={"spec": bad, "student_id": sid},
    )
    assert resp.status_code == 422


# ── 引用核查 ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_citation_verify_and_eligibility(
    _client, _seed, bypass_auth, monkeypatch
):
    sid = str(_seed["user_id"])
    resp = await _client.post(
        "/v1/citation-check/verify",
        json={
            "segments": [
                {"text": "勾股定理", "refs": [{"kind": "ku", "id": KU_ID}]},
                {"text": "无名引用", "refs": [{"kind": "ku", "id": "ku-nope"}]},
            ],
            "student_id": sid,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["passed"] is False
    assert body["segments"][0]["verdict"] == "pass"
    assert body["segments"][1]["verdict"] == "fail"
    resp = await _client.post(
        "/v1/citation-check/verify",
        json={"segments": [], "student_id": sid},
    )
    assert resp.status_code == 422
    resp = await _client.post(
        "/v1/citation-check/eligibility",
        json={"student_id": sid, "ku_ids": [KU_ID]},
    )
    assert resp.status_code == 200, resp.text
    assert "allowed" in resp.json() and "denied" in resp.json()


# ── 任务板＋日历 ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tasks_crud_move_archive(_client, _seed, bypass_auth):
    sid = str(_seed["user_id"])
    resp = await _client.post(
        "/v1/tasks",
        json={
            "title": "复习勾股定理",
            "status": "todo",
            "due_date": "2026-11-02",
            "position": 0,
            "student_id": sid,
        },
    )
    assert resp.status_code == 200, resp.text
    task = resp.json()
    assert task["status"] == "todo"
    task_id = task["id"]
    resp = await _client.post(
        f"/v1/tasks/{task_id}/move",
        json={"status": "done", "position": 2, "student_id": sid},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "done"
    resp = await _client.post(
        f"/v1/tasks/{task_id}/move",
        json={"status": "doing", "student_id": sid},
    )
    assert resp.status_code == 422
    resp = await _client.get("/v1/tasks", params={"student_id": sid})
    assert resp.status_code == 200
    assert any(item["id"] == task_id for item in resp.json()["items"])
    resp = await _client.post(
        f"/v1/tasks/{task_id}/archive", params={"student_id": sid}
    )
    assert resp.status_code == 200
    assert resp.json()["archived"] is True
    resp = await _client.get("/v1/tasks", params={"student_id": sid})
    assert all(item["id"] != task_id for item in resp.json()["items"])
    resp = await _client.post(
        f"/v1/tasks/{task_id}/restore", params={"student_id": sid}
    )
    assert resp.status_code == 200
    resp = await _client.post(
        "/v1/tasks",
        json={"title": "  ", "student_id": sid},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_calendar_merges_tasks_and_reviews(_client, _seed, bypass_auth):
    sid = str(_seed["user_id"])
    resp = await _client.post(
        "/v1/tasks",
        json={
            "title": "复习",
            "due_date": "2026-11-02",
            "student_id": sid,
        },
    )
    assert resp.status_code == 200, resp.text
    resp = await _client.get(
        "/v1/calendar",
        params={
            "student_id": sid,
            "start": "2026-11-02",
            "end": "2026-11-03",
        },
    )
    assert resp.status_code == 200, resp.text
    days = {d["date"]: d["entries"] for d in resp.json()["days"]}
    assert any(e["kind"] == "task" for e in days["2026-11-02"])
    assert any(e["kind"] == "review" for e in days["2026-11-02"])
    resp = await _client.get(
        "/v1/calendar",
        params={"student_id": sid, "start": "2026-11-03", "end": "2026-11-02"},
    )
    assert resp.status_code == 422


# ── 听写 ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dictation_attempt_flow_writes_records(
    _client, _seed, bypass_auth, monkeypatch
):
    sid = str(_seed["user_id"])
    await _create_spec(
        _client, _seed, bypass_auth, monkeypatch, "dictation",
        "/v1/dictation/specs", _dictation_spec(),
    )
    await _verify_spec(
        _client, _seed, monkeypatch, "dictation", "/v1/dictation/specs/dic-ag-1/verify"
    )
    _as_admin(monkeypatch, "dictation", False)
    resp = await _client.post(
        "/v1/dictation/specs/dic-ag-1/attempts",
        json={"typed_text": "Hello world.", "student_id": sid},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["score"] == 0.5
    assert body["missed_words"] == ["good", "morning"]
    assert body["fsrs_due"]
    resp = await _client.post(
        "/v1/dictation/specs/dic-ag-1/attempts",
        json={"typed_text": "Hello world. Good morning.", "student_id": sid},
    )
    assert resp.status_code == 200
    assert resp.json()["score"] == 1.0
    from obase.db import SessionLocal

    async with SessionLocal() as db:
        rows = (
            await db.execute(
                select(QuestionRecord).where(
                    QuestionRecord.student_id == _seed["user_id"],
                    QuestionRecord.source == "dictation",
                )
            )
        ).scalars().all()
    assert len(rows) == 2
    assert {row.question_text for row in rows} == {"good", "morning"}
    assert all(row.is_correct is False for row in rows)


@pytest.mark.asyncio
async def test_dictation_graded_passage_consistency(
    _client, _seed, bypass_auth, monkeypatch
):
    sid = str(_seed["user_id"])
    spec = _dictation_spec("dic-ag-2")
    spec["source"] = {"kind": "graded_passage", "passage_id": PASSAGE_ID}
    await _create_spec(
        _client, _seed, bypass_auth, monkeypatch, "dictation",
        "/v1/dictation/specs", spec,
    )
    bad = _dictation_spec("dic-ag-3")
    bad["segments"] = [{"index": 0, "text": "Totally different text."}]
    bad["source"] = {"kind": "graded_passage", "passage_id": PASSAGE_ID}
    _as_admin(monkeypatch, "dictation", True)
    resp = await _client.post(
        "/v1/dictation/specs",
        json={"spec": bad, "student_id": sid},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_dictation_unverified_spec_attempt_is_404(
    _client, _seed, bypass_auth, monkeypatch
):
    sid = str(_seed["user_id"])
    await _create_spec(
        _client, _seed, bypass_auth, monkeypatch, "dictation",
        "/v1/dictation/specs", _dictation_spec("dic-ag-4"),
    )
    _as_admin(monkeypatch, "dictation", False)
    resp = await _client.post(
        "/v1/dictation/specs/dic-ag-4/attempts",
        json={"typed_text": "Hello world.", "student_id": sid},
    )
    assert resp.status_code == 404


# ── 跟读 ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_shadowing_attempt_with_fake_vendor(
    _client, _seed, bypass_auth, monkeypatch
):
    sid = str(_seed["user_id"])
    await _create_spec(
        _client, _seed, bypass_auth, monkeypatch, "shadowing",
        "/v1/shadowing/specs", _shadowing_spec(),
    )
    await _verify_spec(
        _client, _seed, monkeypatch, "shadowing", "/v1/shadowing/specs/sh-ag-1/verify"
    )
    _as_admin(monkeypatch, "shadowing", False)

    async def fake_score(audio_b64, reference_text):
        return {
            "scores": {
                "overall_score": 82.0,
                "fluency_score": 80.0,
                "accuracy_score": 85.0,
                "word_scores": [{"word": "Hello", "score": 90.0, "issue": None}],
            },
            "transcript": "Hello world",
            "diff": [],
            "weak_words": [],
        }

    monkeypatch.setattr(
        "services.routers.shadowing.score_shadowing", fake_score
    )
    resp = await _client.post(
        "/v1/shadowing/specs/sh-ag-1/attempts",
        json={"sentence_index": 0, "audio_b64": "AAAA", "student_id": sid},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["scores"]["overall_score"] == 82.0
    assert body["transcript"] == "Hello world"
    resp = await _client.post(
        "/v1/shadowing/specs/sh-ag-1/attempts",
        json={"sentence_index": 5, "audio_b64": "AAAA", "student_id": sid},
    )
    assert resp.status_code == 422
    resp = await _client.post(
        "/v1/shadowing/specs/sh-ag-1/attempts",
        json={"sentence_index": 0, "audio_b64": "", "student_id": sid},
    )
    assert resp.status_code == 422


# ── 分级有声 ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_graded_audio_assemble_flow(
    _client, _seed, bypass_auth, monkeypatch
):
    sid = str(_seed["user_id"])
    await _create_spec(
        _client, _seed, bypass_auth, monkeypatch, "graded_audio",
        "/v1/graded-audio/specs", _graded_spec(),
    )
    await _verify_spec(
        _client, _seed, monkeypatch, "graded_audio", "/v1/graded-audio/specs/ga-ag-1/verify"
    )
    _as_admin(monkeypatch, "graded_audio", False)
    resp = await _client.get(
        "/v1/graded-audio/specs/ga-ag-1/assemble", params={"student_id": sid}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert [s["text"] for s in body["sentences"]] == [
        "Hello world.",
        "Good morning.",
    ]
    assert body["word_timings"] is None


# ── 模考 ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_mock_exam_assemble_submit_flow(
    _client, _seed, bypass_auth, monkeypatch
):
    sid = str(_seed["user_id"])
    spec = _mock_spec("mock-ag-1", _seed["wq1"], _seed["wq2"])
    await _create_spec(
        _client, _seed, bypass_auth, monkeypatch, "mock_exams",
        "/v1/mock-exams/specs", spec,
    )
    await _verify_spec(
        _client, _seed, monkeypatch, "mock_exams", "/v1/mock-exams/specs/mock-ag-1/verify"
    )
    _as_admin(monkeypatch, "mock_exams", False)
    resp = await _client.get(
        "/v1/mock-exams/specs/mock-ag-1/assemble", params={"student_id": sid}
    )
    assert resp.status_code == 200, resp.text
    assert "correct_answer" not in resp.text
    assert "1+1=?" in resp.text
    resp = await _client.post(
        "/v1/mock-exams/specs/mock-ag-1/submit",
        json={
            "answers": {str(_seed["wq1"]): "2", str(_seed["wq2"]): "3"},
            "elapsed_seconds": 30,
            "student_id": sid,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["result"]["score"] == 0.5
    assert body["late"] is False
    resp = await _client.post(
        "/v1/mock-exams/specs/mock-ag-1/submit",
        json={
            "answers": {str(_seed["wq1"]): "2"},
            "student_id": sid,
        },
    )
    assert resp.status_code == 422
    resp = await _client.post(
        "/v1/mock-exams/specs/mock-ag-1/submit",
        json={
            "answers": {str(_seed["wq1"]): "2", str(_seed["wq2"]): "4"},
            "elapsed_seconds": 61,
            "student_id": sid,
        },
    )
    assert resp.status_code == 200
    assert resp.json()["late"] is True


# ── MCP 只读工具 ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_mcp_readonly_tools(_client, _seed, bypass_auth, monkeypatch):
    from obase.db import SessionLocal
    from services.models import GradedAudioSpec, VideoLessonSpec

    sid = str(_seed["user_id"])
    user_id = _seed["user_id"]
    async with SessionLocal() as db:
        db.add(VideoLessonSpec(
            id="vl-ag-mcp", ku_id=KU_ID, spec=_video_spec("vl-ag-mcp"),
            verified=True, author_id=user_id,
        ))
        db.add(GradedAudioSpec(
            id="ga-ag-mcp", spec=_graded_spec("ga-ag-mcp"),
            verified=False, author_id=user_id,
        ))
        await db.commit()
    try:
        resp = await _client.post(
            "/mcp/GetVideoLesson",
            json={"student_id": sid, "spec_id": "vl-ag-mcp"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["found"] is True
        resp = await _client.post(
            "/mcp/GetGradedAudioSpec",
            json={"student_id": sid, "spec_id": "ga-ag-mcp"},
        )
        assert resp.status_code == 200
        assert resp.json()["found"] is False
        resp = await _client.post(
            "/mcp/GetTaskBoard",
            json={"student_id": sid},
        )
        assert resp.status_code == 200
        assert resp.json()["items"] == []
    finally:
        async with SessionLocal() as db:
            await db.execute(delete(VideoLessonSpec).where(
                VideoLessonSpec.id == "vl-ag-mcp"))
            await db.execute(delete(GradedAudioSpec).where(
                GradedAudioSpec.id == "ga-ag-mcp"))
            await db.commit()
