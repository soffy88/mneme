"""9 项全嫁接：纯函数门禁＋i18n＋迁移（不连生产库，只连 mneme_test）。

方法来源只学方法、干净重写；本文件只测本分支新增的纯函数与迁移。
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

import pytest

from services.citation_check import check_citations
from services.dictation import (
    compute_dictation_schedule,
    diff_words,
    grade_dictation,
    self_written_passages,
    tokenize,
    verify_dictation_spec,
)
from services.graded_audio import assemble_graded_audio, verify_graded_audio_spec
from services.i18n import CATALOG, negotiate_language, t
from services.mock_exam import (
    assemble_mock_exam,
    score_mock_exam,
    verify_mock_exam_spec,
)
from services.retrieval_eval import (
    METRIC_KEYS,
    eval_diff,
    score_ranking,
    score_rankings,
)
from services.shadowing import score_shadowing, verify_shadowing_spec
from services.task_board import (
    apply_move,
    build_calendar,
    sort_tasks,
    validate_task_payload,
)
from services.video_lesson import (
    advance_progress,
    assemble_video_lesson,
    triangle_angle_sum_spec,
    verify_video_lesson,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _bi(zh, en):
    return {"zh": zh, "en": en}


def _dictation_spec(spec_id="dic-test-1"):
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


def _shadowing_spec(spec_id="sh-test-1"):
    return {
        "id": spec_id,
        "title": _bi("跟读练习", "Shadowing practice"),
        "language": "en",
        "level": 1,
        "target_sentences": ["Hello world.", "Good morning."],
    }


def _graded_spec(spec_id="ga-test-1"):
    return {
        "id": spec_id,
        "title": _bi("分级有声", "Graded audio"),
        "language": "en",
        "level": 1,
        "text": "Hello world. Good morning.",
        "source": {"kind": "self_written"},
    }


def _mock_spec(spec_id="mock-test-1", q1="q1", q2="q2"):
    return {
        "id": spec_id,
        "title": _bi("模考", "Mock exam"),
        "subject": "math",
        "level": 1,
        "sections": [
            {
                "name": _bi("第一部分", "Section one"),
                "seconds": 60,
                "question_ids": [q1, q2],
            }
        ],
        "total_seconds": 60,
    }


# ── i18n ─────────────────────────────────────────────────────────────────


def test_catalog_every_key_has_zh_and_en():
    assert CATALOG, "catalog must not be empty"
    for key, entry in CATALOG.items():
        assert set(entry) == {"zh", "en"}, key
        assert entry["zh"].strip() and entry["en"].strip(), key


def test_negotiate_language_prefers_explicit_then_header_then_default():
    assert negotiate_language("en-US,en;q=0.9,zh;q=0.8", None) == "en"
    assert negotiate_language("zh-CN,zh;q=0.9", None) == "zh"
    assert negotiate_language("fr-FR", None) == "zh"
    assert negotiate_language(None, None) == "zh"
    assert negotiate_language("en", "zh") == "zh"
    assert negotiate_language("zh", "en") == "en"
    assert negotiate_language(None, "fr") == "zh"


def test_t_falls_back_to_key_itself_when_missing():
    assert t("no.such.key", "zh") == "no.such.key"
    assert t("video_lesson.not_found", "en") == "Video lesson spec not found"
    assert t("video_lesson.not_found", "fr") == "视频课规格不存在"


def test_router_visible_strings_all_have_catalog_entries():
    """新路由每个 t("key") 字面量都必须在 CATALOG 有 zh＋en。"""
    router_dir = REPO_ROOT / "services" / "routers"
    names = [
        "video_lessons.py",
        "citation_check.py",
        "tasks.py",
        "calendar.py",
        "dictation.py",
        "shadowing.py",
        "graded_audio.py",
        "mock_exams.py",
    ]
    used: set[str] = set()
    for name in names:
        text = (router_dir / name).read_text()
        used.update(
            re.findall(r"""(?<![A-Za-z_])t\(\s*["']([^"']+)["']""", text)
        )
    assert used, "routers must use t() for user-visible strings"
    missing = sorted(k for k in used if k not in CATALOG)
    assert missing == [], f"catalog missing keys used by routers: {missing}"


# ── 视频课 ───────────────────────────────────────────────────────────────


def test_triangle_reference_spec_passes_and_assembles():
    spec = triangle_angle_sum_spec()
    check = verify_video_lesson(spec, set())
    assert check.passed, [i.to_dict() for i in check.issues]
    assembled = assemble_video_lesson(spec)
    assert assembled["scenes"], "assembled lesson must carry scenes"
    assert len(assembled["captions"]) == 3


def test_video_lesson_rejects_verified_field_and_bad_scene():
    spec = triangle_angle_sum_spec()
    spec["verified"] = True
    check = verify_video_lesson(spec, set())
    assert not check.passed
    assert any(i.code == "verified_field_forbidden" for i in check.issues)


def test_advance_progress_is_sequential_only():
    progress, event = advance_progress({}, 0, 3)
    assert event is None
    assert progress == {"next_scene": 1, "completed": [0]}
    _, event = advance_progress(progress, 2, 3)
    assert event == "out_of_order"
    _, event = advance_progress({"next_scene": 3, "completed": [0, 1, 2]}, 3, 3)
    assert event == "out_of_range"


# ── 听写 ─────────────────────────────────────────────────────────────────


def test_dictation_tokenize_and_diff():
    assert tokenize("Hello, world!") == ["hello", "world"]
    results = diff_words(["hello", "world"], ["hello", "word"])
    assert [r["status"] for r in results] == ["correct", "wrong"]


def test_dictation_grade_perfect_and_partial():
    segments = _dictation_spec()["segments"]
    perfect = grade_dictation(segments, "Hello world. Good morning.")
    assert perfect["score"] == 1.0
    assert perfect["missed_words"] == []
    partial = grade_dictation(segments, "Hello world.")
    assert partial["score"] == 0.5
    assert partial["missed_words"] == ["good", "morning"]
    assert partial["segments"][1]["score"] == 0.0


def test_dictation_schedule_uses_detached_card():
    card, due = compute_dictation_schedule(all_correct=True)
    assert isinstance(card, dict)
    assert isinstance(due, datetime)
    assert due.tzinfo is not None
    card2, due2 = compute_dictation_schedule(
        all_correct=False, previous_card=card
    )
    assert isinstance(card2, dict) and isinstance(due2, datetime)


def test_dictation_spec_gates():
    gates, issues = verify_dictation_spec(_dictation_spec())
    assert all(gates.values()) and not issues
    bad = _dictation_spec()
    bad["segments"] = [{"index": 1, "text": "Hello world."}]
    gates, issues = verify_dictation_spec(bad)
    assert not all(gates.values())
    assert any(i.code == "bad_segment_index" for i in issues)
    forbidden = _dictation_spec()
    forbidden["verified"] = False
    _, issues = verify_dictation_spec(forbidden)
    assert any(i.code == "verified_field_forbidden" for i in issues)


def test_self_written_passages_cover_levels_1_to_3():
    passages = self_written_passages()
    assert len(passages) == 3
    assert sorted(p["level"] for p in passages) == [1, 2, 3]
    for passage in passages:
        texts = [s["text"] for s in passage["segments"]]
        assert texts and all(t.strip() for t in texts)
        assert passage["source"]["kind"] == "self_written"


# ── 跟读 ─────────────────────────────────────────────────────────────────


def test_shadowing_spec_gates():
    gates, issues = verify_shadowing_spec(_shadowing_spec())
    assert all(gates.values()) and not issues
    bad = _shadowing_spec()
    bad["target_sentences"] = []
    gates, issues = verify_shadowing_spec(bad)
    assert not all(gates.values())
    assert any(i.code == "missing_sentences" for i in issues)


@pytest.mark.asyncio
async def test_score_shadowing_with_injected_vendors():
    async def fake_pron(audio_b64, reference_text):
        return {
            "overall_score": 82.0,
            "fluency_score": 80.0,
            "accuracy_score": 85.0,
            "word_scores": [
                {"word": "Hello", "score": 90.0, "issue": None},
                {"word": "world", "score": 40.0, "issue": "low"},
            ],
        }

    async def fake_stt(audio_b64):
        return "Hello word"

    result = await score_shadowing(
        "AAAA", "Hello world.", pron_fn=fake_pron, stt_fn=fake_stt
    )
    assert result["scores"]["overall_score"] == 82.0
    assert result["transcript"] == "Hello word"
    assert result["scores"]["word_scores"][1]["word"] == "world"
    assert any(w["word"] == "world" for w in result["weak_words"])


@pytest.mark.asyncio
async def test_score_shadowing_rejects_empty_audio():
    with pytest.raises(ValueError):
        await score_shadowing("", "Hello world.")


# ── 分级有声 ─────────────────────────────────────────────────────────────


def test_graded_audio_spec_and_assemble_without_alignment():
    gates, issues = verify_graded_audio_spec(_graded_spec())
    assert all(gates.values()) and not issues
    assembled = assemble_graded_audio(_graded_spec())
    assert [s["text"] for s in assembled["sentences"]] == [
        "Hello world.",
        "Good morning.",
    ]
    assert assembled["word_timings"] is None
    assert assembled["highlight_level"] == "sentence"


def test_graded_audio_alignment_length_is_fail_closed():
    spec = _graded_spec()
    spec["alignment"] = [
        {"word": "Hello", "start_ms": 0, "end_ms": 400},
    ]
    gates, issues = verify_graded_audio_spec(spec)
    assert not all(gates.values())
    assert any(i.code == "alignment_length" for i in issues)


# ── 模考 ─────────────────────────────────────────────────────────────────


def test_mock_exam_spec_gates():
    gates, issues = verify_mock_exam_spec(_mock_spec(), {"q1", "q2"})
    assert all(gates.values()) and not issues
    dup = _mock_spec()
    dup["sections"][0]["question_ids"] = ["q1", "q1"]
    gates, issues = verify_mock_exam_spec(dup, {"q1", "q2"})
    assert any(i.code == "duplicate_question" for i in issues)
    missing = _mock_spec()
    gates, issues = verify_mock_exam_spec(missing, {"q1"})
    assert any(i.code == "question_not_found" for i in issues)
    mismatch = _mock_spec()
    mismatch["total_seconds"] = 120
    gates, issues = verify_mock_exam_spec(mismatch, {"q1", "q2"})
    assert any(i.code == "total_mismatch" for i in issues)


def test_mock_exam_assemble_never_includes_answers():
    questions = [
        {"id": "q1", "question_text": "1+1=?", "subject": "math", "correct_answer": "2"},
        {"id": "q2", "question_text": "2+2=?", "subject": "math", "correct_answer": "4"},
    ]
    assembled = assemble_mock_exam(_mock_spec(), questions)
    dumped = json.dumps(assembled, ensure_ascii=False)
    assert '"correct_answer"' not in dumped
    assert "1+1=?" in dumped


def test_mock_exam_scoring_uses_deterministic_graders():
    spec = _mock_spec()
    questions = [
        {"id": "q1", "question_text": "1+1=?", "subject": "math", "correct_answer": "2"},
        {"id": "q2", "question_text": "2+2=?", "subject": "math", "correct_answer": "4"},
    ]
    result = score_mock_exam(spec, questions, {"q1": "2", "q2": "3"})
    assert result["correct"] == 1
    assert result["total"] == 2
    assert result["score"] == 0.5
    assert result["late"] is False
    late = score_mock_exam(spec, questions, {"q1": "2", "q2": "4"}, late=True)
    assert late["score"] == 1.0 and late["late"] is True


# ── 任务板 ───────────────────────────────────────────────────────────────


def test_task_payload_validation():
    assert validate_task_payload({"title": "复习", "status": "todo", "position": 0}) == []
    issues = validate_task_payload({"title": "  ", "status": "todo", "position": 0})
    assert any(i.code == "empty_title" for i in issues)
    issues = validate_task_payload(
        {"title": "x", "status": "doing", "position": 0}
    )
    assert any(i.code == "bad_status" for i in issues)
    issues = validate_task_payload(
        {"title": "x", "status": "todo", "due_date": "2026-13-40", "position": 0}
    )
    assert any(i.code == "bad_due_date" for i in issues)


def test_apply_move_only_touches_status_and_position():
    task = {"title": "x", "status": "todo", "position": 0}
    updated, issues = apply_move(task, status="done", position=3)
    assert issues == []
    assert updated["status"] == "done" and updated["position"] == 3
    assert updated["title"] == "x"
    _, issues = apply_move(task, status="doing")
    assert any(i.code == "bad_status" for i in issues)
    _, issues = apply_move(task, position=-1)
    assert any(i.code == "bad_position" for i in issues)


def test_sort_tasks_archived_last_then_position():
    tasks = [
        {"id": "a", "position": 2, "created_at": "2026-11-02T00:00:00", "archived": False},
        {"id": "b", "position": 1, "created_at": "2026-11-02T00:00:00", "archived": False},
        {"id": "c", "position": 0, "created_at": "2026-11-02T00:00:00", "archived": True},
    ]
    assert [t["id"] for t in sort_tasks(tasks)] == ["b", "a", "c"]


def test_build_calendar_merges_tasks_and_reviews_in_window():
    from datetime import date

    start = date(2026, 11, 2)
    end = date(2026, 11, 3)
    days = build_calendar(
        [
            {"id": "t1", "title": "复习", "status": "todo", "archived": False, "due_date": "2026-11-02"},
            {"id": "t2", "title": "过期", "status": "todo", "archived": False, "due_date": "2026-11-01"},
        ],
        [{"wrong_question_id": "w1", "subject": "math", "fsrs_due": "2026-11-03T09:00:00+00:00"}],
        start,
        end,
    )
    assert [d["date"] for d in days] == ["2026-11-02", "2026-11-03"]
    assert days[0]["entries"][0]["kind"] == "task"
    assert days[1]["entries"][0]["kind"] == "review"


# ── 引用核查 ─────────────────────────────────────────────────────────────


def test_check_citations_pass_fail_and_empty():
    ok = check_citations(
        [{"text": "勾股定理", "refs": [{"kind": "ku", "id": "ku-1"}]}],
        known_ku_ids={"ku-1"},
        known_textbook_ids=set(),
    )
    assert ok["passed"] is True
    assert ok["segments"][0]["verdict"] == "pass"
    unknown = check_citations(
        [{"text": "勾股定理", "refs": [{"kind": "ku", "id": "ku-9"}]}],
        known_ku_ids={"ku-1"},
        known_textbook_ids=set(),
    )
    assert unknown["passed"] is False
    assert unknown["segments"][0]["issues"][0]["code"] == "unknown_ku"
    missing = check_citations(
        [{"text": "无引用", "refs": []}],
        known_ku_ids={"ku-1"},
        known_textbook_ids=set(),
    )
    assert missing["segments"][0]["verdict"] == "fail"
    empty = check_citations([], known_ku_ids=set(), known_textbook_ids=set())
    assert empty["passed"] is False
    assert empty["issues"][0]["code"] == "empty_segments"


# ── 检索评估 ─────────────────────────────────────────────────────────────


def test_retrieval_eval_metrics_and_baseline_pin():
    assert METRIC_KEYS == ("recall@k", "precision@k", "ndcg@k", "mrr", "map", "hit@k")
    perfect = score_ranking(["a", "b"], {"a"}, 5)
    assert perfect["recall@k"] == 1.0 and perfect["hit@k"] == 1.0
    empty_gold = score_ranking(["a"], set(), 5)
    assert all(v == 0.0 for v in empty_gold.values())
    cases = []
    for line in (REPO_ROOT / "tests" / "fixtures" / "retrieval_eval_qa.jsonl").read_text().splitlines():
        case = json.loads(line)
        case["gold"] = set(case["gold"])
        cases.append(case)
    assert len(cases) >= 20
    report = score_rankings(cases, 5)
    baseline = json.loads(
        (REPO_ROOT / "tests" / "fixtures" / "retrieval_eval_baseline.json").read_text()
    )
    assert report == baseline
    diff = eval_diff(baseline, report)
    assert diff["changed_cases"] == [] or all(
        d == 0.0 for d in diff["metric_deltas"].values()
    )


# ── 迁移 ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_migration_upgrades_to_single_head():
    """迁移链单头 + 本迁移 upgrade/downgrade 真跑（克隆库，跑完即删）。

    复用 test_teaching_figure_spec.py 的克隆库模式：共享 mneme_test 的
    版本行现指他分支 revision、且全链从空库 upgrade 在既有 word-atlas
    迁移处已断——均为本迁移之外的既有状态，本次不越界修。故克隆库、
    stamp 到父 revision、只跑本迁移。绝不碰生产库。
    """
    import os
    import subprocess
    import sys

    import asyncpg
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from sqlalchemy.engine.url import make_url

    base_url = os.environ["DATABASE_URL"]
    url = make_url(base_url)
    assert url.database == "mneme_test", "迁移测试只许以 mneme_test 为基"
    scratch = "mneme_test_ag"
    dsn = (
        f"postgresql://{url.username}:{url.password}"
        f"@{url.host}:{url.port}/postgres"
    )
    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    script = ScriptDirectory.from_config(cfg)
    assert tuple(script.get_heads()) == ("wnb1a2b3c4d5e",)
    assert script.get_revision("all1a2b3c4d5e").down_revision == "tfg1a2b3c4d5e"
    assert script.get_revision("wnb1a2b3c4d5e").down_revision == "all1a2b3c4d5e"
    from services.routers.health import EXPECTED_MIGRATION_HEAD

    assert EXPECTED_MIGRATION_HEAD == "wnb1a2b3c4d5e"

    def _alembic(*args):
        env = dict(os.environ)
        env["DATABASE_URL"] = (
            f"postgresql+asyncpg://{url.username}:{url.password}"
            f"@{url.host}:{url.port}/{scratch}"
        )
        env["PYTHONPATH"] = str(REPO_ROOT)
        proc = subprocess.run(
            [sys.executable, "-m", "alembic", *args],
            cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=180,
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
            for table in (
                "video_lesson_specs",
                "dictation_specs",
                "dictation_attempts",
                "shadowing_specs",
                "shadowing_attempts",
                "graded_audio_specs",
                "mock_exam_specs",
                "mock_exam_attempts",
                "study_tasks",
                "exam_sheets",
                "exam_sheet_results",
                "animated_explanation_specs",
            ):
                await conn.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
            await conn.execute("DELETE FROM alembic_version")
            await conn.execute(
                "INSERT INTO alembic_version VALUES ('tfg1a2b3c4d5e')"
            )
        finally:
            await conn.close()
        _alembic("upgrade", "head")
        conn = await asyncpg.connect(dsn.rsplit("/", 1)[0] + f"/{scratch}")
        try:
            version = await conn.fetchval(
                "SELECT version_num FROM alembic_version"
            )
            tables = await conn.fetch(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public' "
                "AND tablename IN ('video_lesson_specs','dictation_specs',"
                "'dictation_attempts','shadowing_specs','shadowing_attempts',"
                "'graded_audio_specs','mock_exam_specs','mock_exam_attempts',"
                "'study_tasks')"
            )
            has_index = await conn.fetchval(
                "SELECT indexname FROM pg_indexes WHERE "
                "indexname = 'ix_study_tasks_student_due'"
            )
        finally:
            await conn.close()
        assert version == "wnb1a2b3c4d5e"
        assert len(tables) == 9, [dict(r) for r in tables]
        assert has_index == "ix_study_tasks_student_due"
        _alembic("downgrade", "tfg1a2b3c4d5e")
        conn = await asyncpg.connect(dsn.rsplit("/", 1)[0] + f"/{scratch}")
        try:
            version = await conn.fetchval(
                "SELECT version_num FROM alembic_version"
            )
            has_table = await conn.fetchval(
                "SELECT to_regclass('public.study_tasks')"
            )
        finally:
            await conn.close()
        assert version == "tfg1a2b3c4d5e"
        assert has_table is None
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
