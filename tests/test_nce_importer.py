"""NCE importer unit tests: manifest, book.json, LRC, normalization,
stable identity, tokenization, audio duration, validator gates."""

from __future__ import annotations

import json
import os
import uuid

import pytest

from scripts.nce_importer.audio import mp3_duration_ms
from scripts.nce_importer.extractor import VocabularyExtractor
from scripts.nce_importer.lrc import check_timestamp_order, parse_lrc
from scripts.nce_importer.manifest import NCEManifestLoader
from scripts.nce_importer.normalizer import (
    normalize_raw_text,
    normalize_sentence_text,
)
from scripts.nce_importer.resolver import get_vid
from scripts.nce_importer.validator import NCEImportValidator

MANIFEST_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "scripts",
    "nce_importer",
    "pinned_manifest.json",
)


# ---------- manifest ----------


def test_pinned_manifest_loads_and_is_pinned():
    manifest = NCEManifestLoader().load(MANIFEST_PATH)
    assert manifest.source_repository == "iChochy/NCE"
    assert manifest.source_commit == "0a92ab5af50e2898a104f15eac7adb00f17bd96b"
    assert manifest.pinned
    assert manifest.content_rights == "RESTRICTED_EXTERNAL_EDUCATIONAL_CONTENT"
    assert manifest.redistribution_allowed is False
    assert manifest.code_license == "MIT"


def test_manifest_covers_all_8_books():
    manifest = NCEManifestLoader().load(MANIFEST_PATH)
    keys = {(b.book_key, b.edition) for b in manifest.books}
    assert keys == {
        ("NCE1", "CURRENT"),
        ("NCE2", "CURRENT"),
        ("NCE3", "CURRENT"),
        ("NCE4", "CURRENT"),
        ("NCE1(85)", "1985"),
        ("NCE2(85)", "1985"),
        ("NCE3(85)", "1985"),
        ("NCE4(85)", "1985"),
    }
    for b in manifest.books:
        assert b.book_json_url.endswith("/book.json")
        assert "{filename}" in b.audio_url
        assert "{filename}" in b.lrc_url


def test_data_json_manifest_parsing():
    """data.json from the pinned commit parses into the 8-book manifest."""
    data = {
        "books": [
            {"key": "NCE1", "title": "NCE1 English Book", "path": "https://nce.mleo.site/NCE1"},
            {"key": "NCE1(85)", "title": "NCE1 English Book(85)", "path": "https://85.mleo.site/NCE1"},
        ]
    }
    manifest = NCEManifestLoader().parse(
        {
            "source_repository": "iChochy/NCE",
            "source_commit": "abc123",
            "books": [
                {
                    "book_key": b["key"],
                    "edition": "1985" if "(85)" in b["key"] else "CURRENT",
                    "book_resource_url": b["path"],
                    "book_json_url": b["path"] + "/book.json",
                    "audio_url": b["path"] + "/{filename}.mp3",
                    "lrc_url": b["path"] + "/{filename}.lrc",
                }
                for b in data["books"]
            ],
        }
    )
    assert len(manifest.books) == 2
    assert manifest.books[0].edition == "CURRENT"
    assert manifest.books[1].edition == "1985"


# ---------- book.json parsing ----------


def test_book_json_current_edition():
    data = {
        "name": "NCE",
        "level": "1st Level",
        "cover": "NCE1.jpg",
        "units": [
            {"title": "001&002.Excuse Me", "filename": "001&002.Excuse Me"},
            {"title": "003&004.Sorry, Sir.", "filename": "003&004.Sorry, Sir."},
        ],
    }
    assert data["units"][0]["filename"] == "001&002.Excuse Me"
    assert len(data["units"]) == 2


def test_book_json_85_edition():
    data = {
        "name": "NCE1 (British Accent)",
        "level": "1st Level",
        "cover": "cover.jpg",
        "units": [{"title": "001. Excuse Me", "filename": "NCE1(1985 British accent)_001"}],
    }
    assert "1985" in data["units"][0]["filename"]
    assert data["name"] != "NCE"


# ---------- LRC parser ----------


def test_lrc_bilingual_split():
    text = "[00:02.71]Excuse me! | 打扰一下！"
    result = parse_lrc(text)
    assert len(result.lines) == 1
    line = result.lines[0]
    assert line.start_ms == 2710
    assert line.english_text == "Excuse me!"
    assert line.chinese_text == "打扰一下！"


def test_lrc_three_digit_milliseconds():
    result = parse_lrc("[00:01.456]Hello there")
    assert result.lines[0].start_ms == 1456


def test_lrc_two_digit_milliseconds():
    result = parse_lrc("[00:01.45]Hello")
    assert result.lines[0].start_ms == 1450


def test_lrc_english_only_line():
    result = parse_lrc("[00:05.00]Just English, no translation")
    assert len(result.lines) == 1
    assert result.lines[0].english_text == "Just English, no translation"
    assert result.lines[0].chinese_text is None


def test_lrc_comments_and_empty_lines_skipped():
    text = "# a comment\n\n[al:album]\n[ar:artist]\n[00:01.00]Hi | 你好"
    result = parse_lrc(text)
    assert len(result.lines) == 1
    assert result.skipped_meta == 2
    assert result.skipped_empty == 2


def test_lrc_timestamp_ordering_sorted():
    text = "[00:10.00]Second | 第二\n[00:02.00]First | 第一\n"
    result = parse_lrc(text)
    assert [l.start_ms for l in result.lines] == [2000, 10000]
    assert check_timestamp_order(result.lines) == []


def test_lrc_seconds_ge_60_skipped():
    result = parse_lrc("[00:75.00]Bad | 坏")
    assert result.lines == []
    assert result.skipped_invalid == 1


def test_lrc_exact_duplicate_lines_deduped():
    text = "[00:01.00]Hi | 你好\n[00:02.00]Bye | 再见\n[00:01.00]Hi | 你好"
    result = parse_lrc(text)
    assert len(result.lines) == 2
    assert result.skipped_duplicates == 1


# ---------- sentence normalization ----------


def test_sentence_normalization_nfkc_and_whitespace():
    assert normalize_sentence_text("  Hello   world  ") == "Hello world"
    # NFKC: fullwidth Ａ -> A
    assert normalize_sentence_text("Ａbc") == "Abc"


def test_raw_text_preserved():
    assert normalize_raw_text("  [00:01.00]Hi | 你好  ") == "[00:01.00]Hi | 你好"


# ---------- stable identity ----------


def test_stable_uuid_identity():
    a = str(uuid.uuid5(uuid.NAMESPACE_URL, "mneme://book/NCE/NEW_CONCEPT_ENGLISH/CURRENT/NCE1"))
    b = str(uuid.uuid5(uuid.NAMESPACE_URL, "mneme://book/NCE/NEW_CONCEPT_ENGLISH/CURRENT/NCE1"))
    assert a == b
    c = str(uuid.uuid5(uuid.NAMESPACE_URL, "mneme://book/NCE/NEW_CONCEPT_ENGLISH/1985/NCE1"))
    assert a != c


def test_get_vid_reuses_k12_namespace():
    # Must equal the K12 importer's get_vid for the same normalized form.
    from scripts.import_english_k12_vocab import get_vid as k12_get_vid

    assert get_vid("airport") == k12_get_vid("airport")


# ---------- tokenization / canonical reuse ----------


def test_extractor_word_tokens():
    extractor = VocabularyExtractor()
    result = extractor.extract("Excuse me, is this your handbag?")
    norms = [o.normalized_form for o in result.occurrences]
    assert norms == ["excuse", "me", "is", "this", "your", "handbag"]
    assert result.word_count == 6
    assert result.phrase_count == 0


def test_extractor_airport_canonical_form():
    extractor = VocabularyExtractor()
    for surface in ("Airport", "airport", "AIRPORT"):
        result = extractor.extract(f"The {surface} is big.")
        assert result.occurrences[1].normalized_form == "airport"


def test_extractor_existing_phrase_only():
    extractor = VocabularyExtractor(existing_phrases={"paper cutting"})
    result = extractor.extract("I like paper cutting.")
    norms = [o.normalized_form for o in result.occurrences]
    assert "paper cutting" in norms
    assert result.phrase_count == 1
    # bigram not in existing phrases → two words
    extractor2 = VocabularyExtractor(existing_phrases=set())
    result2 = extractor2.extract("I like paper cutting.")
    assert "paper cutting" not in [o.normalized_form for o in result2.occurrences]


def test_extractor_contractions_and_hyphens():
    extractor = VocabularyExtractor()
    result = extractor.extract("It's well-known, isn't?")
    norms = [o.normalized_form for o in result.occurrences]
    assert "it's" in norms
    assert "well-known" in norms


# ---------- audio duration ----------


def test_mp3_duration_matches_ffprobe():
    sample = os.path.join(os.path.dirname(__file__), "nce_fixtures", "nce_sample.mp3")
    if not os.path.exists(sample):
        pytest.skip("sample mp3 not present")
    data = open(sample, "rb").read()
    assert mp3_duration_ms(data) == 37128


# ---------- validator ----------


def _lesson(sentences):
    from scripts.nce_importer.planner import PlannedLesson

    return PlannedLesson(
        lesson_key="k",
        title="t",
        source_order=1,
        audio_uri=None,
        audio_hash=None,
        audio_duration_ms=None,
        lrc_uri="https://x/y.lrc",
        lrc_hash="ab" * 32,
        sentences=sentences,
    )


def _sent(order, start, end):
    from scripts.nce_importer.planner import PlannedSentence

    return PlannedSentence(
        source_order=order,
        start_ms=start,
        end_ms=end,
        english_text="e",
        chinese_text=None,
        raw_text="r",
        source_line=order,
        source_entry_key=f"k{order}",
    )


def test_validator_clean_plan_passes():
    from scripts.nce_importer.manifest import NCEManifestLoader
    from scripts.nce_importer.planner import CourseImportPlan, PlannedBook

    manifest = NCEManifestLoader().load(MANIFEST_PATH)
    plan = CourseImportPlan(
        scope="NCE",
        series="NEW_CONCEPT_ENGLISH",
        title="New Concept English",
        source_id="iChochy/NCE",
        books=[
            PlannedBook(
                book_key="NCE1",
                edition="CURRENT",
                title="NCE1",
                level="1st Level",
                source_url="https://nce.mleo.site/NCE1",
                source_hash="cd" * 32,
                source_metadata={},
                lessons=[_lesson([_sent(1, 0, 1000), _sent(2, 1000, 2000)])],
            )
        ],
    )
    report = NCEImportValidator().validate(plan, manifest)
    assert report.ok
    assert report.timestamp_order_violations == 0
    assert report.negative_duration == 0


def test_validator_flags_negative_duration():
    from scripts.nce_importer.manifest import NCEManifestLoader
    from scripts.nce_importer.planner import CourseImportPlan, PlannedBook

    manifest = NCEManifestLoader().load(MANIFEST_PATH)
    plan = CourseImportPlan(
        scope="NCE",
        series="NEW_CONCEPT_ENGLISH",
        title="New Concept English",
        source_id="iChochy/NCE",
        books=[
            PlannedBook(
                book_key="NCE1",
                edition="CURRENT",
                title="NCE1",
                level=None,
                source_url="https://nce.mleo.site/NCE1",
                source_hash="cd" * 32,
                source_metadata={},
                lessons=[_lesson([_sent(1, 2000, 1000)])],
            )
        ],
    )
    report = NCEImportValidator().validate(plan, manifest)
    assert not report.ok
    assert report.negative_duration == 1


def test_validator_flags_rights_metadata():
    from scripts.nce_importer.manifest import NCEManifestLoader
    from scripts.nce_importer.planner import CourseImportPlan, PlannedBook

    manifest = NCEManifestLoader().load(MANIFEST_PATH)
    manifest.content_rights = "MIT"
    manifest.redistribution_allowed = True
    plan = CourseImportPlan(
        scope="NCE",
        series="NEW_CONCEPT_ENGLISH",
        title="New Concept English",
        source_id="iChochy/NCE",
        books=[
            PlannedBook(
                book_key="NCE1",
                edition="CURRENT",
                title="NCE1",
                level=None,
                source_url="https://nce.mleo.site/NCE1",
                source_hash="cd" * 32,
                source_metadata={},
                lessons=[_lesson([_sent(1, 0, 1000)])],
            )
        ],
    )
    report = NCEImportValidator().validate(plan, manifest)
    assert not report.ok
    assert any(i.code == "RIGHTS_METADATA" for i in report.issues)
