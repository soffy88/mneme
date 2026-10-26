"""Word Atlas 四题型接线测试（集成-2）。

纯内存部分零数据库依赖；DB 部分只连 mneme_test（拿不到连接时
pytest.skip，不编造、不碰生产库 mneme）。DB 部分用独立 student_key
隔离，跑完删除本测试写入的卡片行；媒体附表与词条行只读不写
（补丁幂等测试除外：它只重施加集成-3 补丁，本身就是幂等操作）。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from services.wordatlas_fsrs import (
    FSRSState,
    Rating,
    build_review_queue,
    is_mastered,
)
from services.wordatlas_review import (
    QUESTION_TYPE_CHOICE,
    QUESTION_TYPE_LISTENING,
    QUESTION_TYPE_PICTURE,
    QUESTION_TYPE_SPELLING,
    build_word_atlas_queue,
    card_key,
    choose_question_type,
    grade_vocab_answer,
    media_mask,
    strip_pos_suffix,
    submit_vocab_answer,
    syn_for_pos,
)

NOW = datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc)


def _card(vocab_id, **kw):
    base = {
        "key": card_key(vocab_id),
        "stability": 10.0,
        "difficulty": 5.0,
        "due": NOW - timedelta(days=2),
        "last_review": NOW - timedelta(days=12),
        "review_count": 3,
    }
    base.update(kw)
    return FSRSState(**base)


def _new(vocab_id):
    return FSRSState(key=card_key(vocab_id))


# ── 队列排序 ──
def test_queue_due_oldest_first_then_new_batch_of_five():
    due_old = _card("due-old", due=NOW - timedelta(days=9))
    due_new = _card("due-new", due=NOW - timedelta(days=1))
    upcoming = _card("upcoming", due=NOW + timedelta(days=3))
    news = [_new(f"new-{i}") for i in range(7)]
    built = build_word_atlas_queue(
        [due_new, upcoming, due_old] + news, NOW, group_size=5
    )
    assert [c.key for c in built["due"]] == [due_old.key, due_new.key]
    assert len(built["new_batch"]) == 5
    assert len(built["new_remaining"]) == 2
    assert [c.key for c in built["queue"]] == [due_old.key, due_new.key] + [
        c.key for c in built["new_batch"]
    ]
    assert [c.key for c in built["upcoming"]] == [upcoming.key]


def test_queue_excludes_short_weight_in_filter_layer():
    # short-weight 的 cefr/note 不动，只在队列过滤层排除：到期态与新词态
    # 都不得进队列。
    cards = [_card("short-weight"), _new("short-weight"), _new("library")]
    built = build_word_atlas_queue(cards, NOW)
    keys = [c.key for c in built["queue"]]
    assert keys == [card_key("library")]
    assert all("short-weight" not in k for k in keys)


def test_queue_matches_module_build_review_queue_when_no_exclusion():
    cards = [_card("a", due=NOW - timedelta(days=2)), _new("b"), _new("c")]
    assert build_word_atlas_queue(cards, NOW) == build_review_queue(
        cards, NOW
    )


# ── 评分映射（四题型共用同一口径）──
@pytest.mark.parametrize("qtype", ["choice", "picture", "listening", "spelling"])
def test_grade_mapping_all_four_types(qtype):
    assert grade_vocab_answer(qtype, {"result": "wrong"}) == Rating.AGAIN
    assert (
        grade_vocab_answer(qtype, {"result": "correct", "latency_ms": 40000})
        == Rating.HARD
    )
    assert (
        grade_vocab_answer(qtype, {"result": "correct", "used_hint": True})
        == Rating.HARD
    )
    assert (
        grade_vocab_answer(qtype, {"result": "correct", "latency_ms": 1500})
        == Rating.EASY
    )
    assert (
        grade_vocab_answer(qtype, {"result": "correct", "latency_ms": 8000})
        == Rating.GOOD
    )


def test_grade_unknown_type_rejected():
    with pytest.raises(ValueError):
        grade_vocab_answer("typing", {"result": "correct"})


# ── skip 不计分（集成定案：None 短路，禁止默认落到 Again）──
def test_skip_and_self_assessment_score_nothing():
    card = _card("library")
    for answer in ({"result": "skip"}, {"result": "correct", "self_assessed": True}):
        assert grade_vocab_answer(QUESTION_TYPE_CHOICE, answer) is None
        new_card, rating, applied, _ = submit_vocab_answer(
            card, QUESTION_TYPE_CHOICE, answer, NOW, session_id="s1"
        )
        assert rating is None and applied is False
        assert new_card is card  # 原卡不动
        assert new_card.stability == 10.0 and new_card.review_count == 3


def test_skip_does_not_consume_first_answer_slot():
    # 跳过后同一节里该词的真实作答仍可计分。
    card = _new("library")
    _, _, applied_skip, ids = submit_vocab_answer(
        card, QUESTION_TYPE_CHOICE, {"result": "skip"}, NOW, session_id="s1"
    )
    assert applied_skip is False
    new_card, rating, applied, _ = submit_vocab_answer(
        card,
        QUESTION_TYPE_SPELLING,
        {"result": "correct", "latency_ms": 8000},
        NOW,
        session_id="s1",
        applied_ids=ids,
    )
    assert applied is True and rating == Rating.GOOD
    assert new_card.review_count == 1


# ── 幂等重答 ──
def test_idempotent_reanswer_same_session():
    card = _new("library")
    first, rating, applied, ids = submit_vocab_answer(
        card,
        QUESTION_TYPE_CHOICE,
        {"result": "wrong"},
        NOW,
        session_id="s1",
        applied_ids=set(),
    )
    assert applied is True and rating == Rating.AGAIN
    second, rating2, applied2, _ = submit_vocab_answer(
        first,
        QUESTION_TYPE_PICTURE,  # 换题型重试也不重复计分
        {"result": "correct", "latency_ms": 1000},
        NOW,
        session_id="s1",
        applied_ids=ids,
    )
    assert applied2 is False and second is first
    assert second.due == first.due and second.review_count == 1


def test_new_session_counts_again():
    card = _new("library")
    _, _, _, ids = submit_vocab_answer(
        card,
        QUESTION_TYPE_CHOICE,
        {"result": "wrong"},
        NOW,
        session_id="s1",
        applied_ids=set(),
    )
    new_card, _, applied, _ = submit_vocab_answer(
        card,
        QUESTION_TYPE_CHOICE,
        {"result": "correct", "latency_ms": 8000},
        NOW,
        session_id="s2",
        applied_ids=ids,
    )
    assert applied is True and new_card.review_count == 1


def test_mastered_threshold_unchanged():
    assert is_mastered(_card("x", stability=21.0)) is True
    assert is_mastered(_card("x", stability=20.9)) is False


# ── syn 词性后缀（集成-3 交代取舍 ②）──
def test_strip_pos_suffix_and_no_cross_pos_syn():
    assert strip_pos_suffix("prison (n.)") == ("prison", "n")
    assert strip_pos_suffix("imprison (v.)") == ("imprison", "v")
    assert strip_pos_suffix("speed") == ("speed", None)
    jail_syn = ["prison (n.)", "imprison (v.)"]
    assert syn_for_pos(jail_syn, "n.") == ["prison"]
    assert syn_for_pos(jail_syn, "v.") == ["imprison"]
    rally_syn = ["gathering (n.)", "mobilise (v.)", "recover (v.)"]
    assert syn_for_pos(rally_syn, "n.") == ["gathering"]
    assert syn_for_pos(rally_syn, "v.") == ["mobilise", "recover"]
    # 展示前已剥离：输出里不得残留 "(n.)" 后缀。
    assert all("(" not in w for w in syn_for_pos(jail_syn, "n."))
    # 无后缀 plain syn 不擅自删词。
    assert syn_for_pos(["speed"], "n.") == ["speed"]


# ── 媒体位与降级 ──
def test_media_mask_bits():
    assert media_mask({}) == 0
    assert (
        media_mask(
            {
                "has_img": True,
                "has_thumb": True,
                "has_audio_uk": True,
                "has_audio_us": True,
                "has_audio_ex": True,
                "has_audio_ex2": True,
            }
        )
        == 63
    )
    assert media_mask({"has_audio_ex2": True}) == 32


def test_choose_question_type_falls_back_to_choice():
    assert (
        choose_question_type(
            QUESTION_TYPE_LISTENING, {"has_audio_uk": False}, accent="uk"
        )
        == QUESTION_TYPE_CHOICE
    )
    assert (
        choose_question_type(
            QUESTION_TYPE_LISTENING, {"has_audio_us": True}, accent="us"
        )
        == QUESTION_TYPE_LISTENING
    )
    assert (
        choose_question_type(QUESTION_TYPE_PICTURE, {"has_img": False})
        == QUESTION_TYPE_CHOICE
    )
    assert (
        choose_question_type(QUESTION_TYPE_PICTURE, {"has_img": True})
        == QUESTION_TYPE_PICTURE
    )


# ── DB 部分（只连 mneme_test；无连接则 skip）──
def _db_conn():
    try:
        import psycopg2
    except ImportError:
        pytest.skip("无 psycopg2")
    url = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not url or "mneme_test" not in url:
        pytest.skip("无 mneme_test DSN")
    try:
        conn = psycopg2.connect(url)
    except Exception:
        pytest.skip("连不上 mneme_test")
    return conn


def test_db_tables_and_media_counts():
    conn = _db_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass('word_atlas_fsrs_cards')")
            assert cur.fetchone()[0] == "word_atlas_fsrs_cards"
            cur.execute("SELECT to_regclass('vocab_media_availability')")
            assert cur.fetchone()[0] == "vocab_media_availability"
            cur.execute(
                "SELECT count(*) FILTER (WHERE has_img AND has_thumb"
                " AND has_audio_uk AND has_audio_us AND has_audio_ex"
                " AND has_audio_ex2),"
                " count(*) FILTER (WHERE NOT has_audio_ex2),"
                " count(*) FILTER (WHERE NOT has_img),"
                " count(*) FROM vocab_media_availability"
            )
            full6, only_missing_ex2, missing_img, total = cur.fetchone()
        # 干跑统计（集成-3）：全有 1,011、仅缺 ex2 6,287、其余缺失 0。
        assert (total, full6, only_missing_ex2, missing_img) == (
            7298,
            1011,
            6287,
            0,
        )
    finally:
        conn.close()


def test_db_answer_roundtrip_skip_and_idempotent():
    from services.wordatlas_review import (
        answer_question,
        fetch_review_queue,
        load_card,
    )

    conn = _db_conn()
    student_key = "test-" + uuid.uuid4().hex[:12]
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM vocab_units WHERE id = 'library'"
            )
            assert cur.fetchone()[0] == 1
        # 只读队列：short-weight 不得出现（过滤层），且不写库。
        queue = fetch_review_queue(conn, NOW, student_key=student_key)
        assert all(
            item["vocab_id"] != "short-weight" for item in queue["queue"]
        )
        # skip：不写库。
        res = answer_question(
            conn,
            "library",
            QUESTION_TYPE_CHOICE,
            {"result": "skip"},
            NOW,
            session_id="db-s1",
            student_key=student_key,
        )
        assert res["rating"] is None and res["applied"] is False
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM word_atlas_fsrs_cards"
                " WHERE student_key = %s AND vocab_id = 'library'",
                (student_key,),
            )
            assert cur.fetchone()[0] == 0
        # 计分：写回 due；重读一致。
        res = answer_question(
            conn,
            "library",
            QUESTION_TYPE_CHOICE,
            {"result": "correct", "latency_ms": 1500},
            NOW,
            session_id="db-s1",
            student_key=student_key,
        )
        assert res["rating"] == "EASY" and res["applied"] is True
        assert res["due"] is not None and res["review_count"] == 1
        card, _ = load_card(conn, "library", student_key)
        assert card.due is not None and card.due.isoformat() == res["due"]
        # 同轮重答：due 不变。
        res2 = answer_question(
            conn,
            "library",
            QUESTION_TYPE_PICTURE,
            {"result": "correct", "latency_ms": 1000},
            NOW,
            session_id="db-s1",
            student_key=student_key,
        )
        assert res2["applied"] is False and res2["due"] == res["due"]
    finally:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM word_atlas_fsrs_cards WHERE student_key = %s",
                (student_key,),
            )
        conn.commit()
        conn.close()


def test_db_patch_reapply_is_idempotent():
    """补丁重施加幂等：第二次跑补丁脚本应全为 SKIPPED/RETAINED，退出 0，
    且 8 项补丁值与补丁文件一致。"""
    import psycopg2  # noqa: F401  # 仅作可用性检查

    conn = _db_conn()
    root = Path(__file__).resolve().parents[1]
    script = root / "scripts" / "apply_word_atlas_vocab_patches.py"
    patches = root / "scripts" / "word-atlas-vocab-patches.json"
    if not script.exists() or not patches.exists():
        pytest.skip("补丁脚本/文件未落盘")
    env = dict(os.environ)
    proc = subprocess.run(
        [sys.executable, str(script), "--patches", str(patches)],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]
    assert "CONFLICT" not in proc.stdout and "MISSING" not in proc.stdout
    data = json.loads(patches.read_text(encoding="utf-8"))
    try:
        with conn.cursor() as cur:
            for p in data["patches"]:
                assert p["field"] in {"syn", "family", "note"}
                cur.execute(
                    f"SELECT {p['field']} FROM vocab_units WHERE id = %s",
                    (p["id"],),
                )
                assert cur.fetchone()[0] == p["new"], p["id"]
    finally:
        conn.close()
