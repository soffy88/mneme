"""ContextEngine unit tests: context ranking and recent-seen exclusion.

Pure-logic tests for services/context_engine.py (no DB).
"""

from __future__ import annotations

from services.context_engine import ContextEngine, VocabContext


def _ctx(sid: str, words: int, has_audio: bool = True) -> VocabContext:
    return VocabContext(
        vocabulary_item_id="v1",
        sentence_id=sid,
        english_text=" ".join(["word"] * words),
        chinese_text=None,
        start_ms=0 if has_audio else None,
        end_ms=1000 if has_audio else None,
        audio_uri="x.mp3" if has_audio else None,
        source="NCE",
        lesson_id="l1",
    )


def test_rank_prefers_shorter_sentences():
    engine = ContextEngine(db=None)  # type: ignore[arg-type]
    long = _ctx("long", 20)
    short = _ctx("short", 5)
    ranked = engine.rank_contexts([long, short])
    assert ranked[0].sentence_id == "short"


def test_rank_prefers_audio():
    engine = ContextEngine(db=None)  # type: ignore[arg-type]
    with_audio = _ctx("a", 10, has_audio=True)
    no_audio = _ctx("b", 10, has_audio=False)
    ranked = engine.rank_contexts([no_audio, with_audio])
    assert ranked[0].sentence_id == "a"


def test_recently_seen_deprioritized():
    engine = ContextEngine(db=None)  # type: ignore[arg-type]
    seen = _ctx("seen", 5)
    fresh = _ctx("fresh", 5)
    ranked = engine.rank_contexts([seen, fresh], recently_seen={"seen"})
    assert ranked[0].sentence_id == "fresh"
    assert ranked[1].sentence_id == "seen"


def test_empty_contexts():
    engine = ContextEngine(db=None)  # type: ignore[arg-type]
    assert engine.rank_contexts([]) == []
