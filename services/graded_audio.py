"""Graded audio + word highlighting (Parroto method, clean rewrite).

A passage plus optional real word-level timestamps. When alignment is
absent, only sentence-level highlighting is offered: word timings are
NEVER invented from averages. Audio is never synthesized here; the
spec carries the TTS text.
"""

from __future__ import annotations

import re
from typing import Any, Mapping, Optional

from services.dictation import tokenize

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


class GradedAudioIssue:
    def __init__(self, field: str, code: str, message: str) -> None:
        self.field = field
        self.code = code
        self.message = message

    def to_dict(self) -> dict[str, str]:
        return {"field": self.field, "code": self.code, "message": self.message}


def _is_bilingual(value: object) -> bool:
    return (
        isinstance(value, dict)
        and isinstance(value.get("zh"), str)
        and value["zh"].strip() != ""
        and isinstance(value.get("en"), str)
        and value["en"].strip() != ""
    )


def _normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def verify_graded_audio_spec(
    spec: Mapping[str, Any], passage_text: Optional[str] = None
) -> tuple[dict[str, bool], list[GradedAudioIssue]]:
    """Six gates; alignment and passage consistency are fail-closed."""
    gates: dict[str, bool] = {f"g{i}": True for i in range(1, 7)}
    issues: list[GradedAudioIssue] = []

    def fail(gate: str, issue: GradedAudioIssue) -> None:
        gates[gate] = False
        issues.append(issue)

    if not isinstance(spec, dict):
        return gates, [GradedAudioIssue("", "not_an_object", "spec must be an object")]
    spec_id = spec.get("id")
    if not isinstance(spec_id, str) or not spec_id or len(spec_id) > 100:
        fail("g1", GradedAudioIssue("id", "bad_id", "id must be a non-empty string of at most 100 chars"))
    if not _is_bilingual(spec.get("title")):
        fail("g2", GradedAudioIssue("title", "bad_title", "title must carry non-empty zh and en"))
    if spec.get("language") not in ("zh", "en"):
        fail("g2", GradedAudioIssue("language", "bad_language", "language must be zh or en"))
    level = spec.get("level")
    if not isinstance(level, int) or isinstance(level, bool) or not 1 <= level <= 5:
        fail("g2", GradedAudioIssue("level", "bad_level", "level must be an integer from 1 to 5"))
    text = spec.get("text")
    if not isinstance(text, str) or not text.strip():
        fail("g3", GradedAudioIssue("text", "empty_text", "text must be non-empty"))
        text = ""
    source = spec.get("source")
    if not isinstance(source, dict) or source.get("kind") not in ("self_written", "graded_passage"):
        fail("g3", GradedAudioIssue("source", "bad_source", "source kind must be self_written or graded_passage"))
    elif source.get("kind") == "graded_passage":
        if not isinstance(source.get("passage_id"), str) or not source["passage_id"]:
            fail("g3", GradedAudioIssue("source.passage_id", "missing_passage_id", "graded_passage source needs a passage_id"))
        elif passage_text is None:
            fail("g3", GradedAudioIssue("source", "unknown_passage", "passage text is required to verify a graded_passage source"))
        elif _normalize_space(text) != _normalize_space(passage_text):
            fail("g3", GradedAudioIssue("text", "passage_mismatch", "text must match the passage text"))
    alignment = spec.get("alignment")
    if alignment is not None:
        if not isinstance(alignment, list) or not alignment:
            fail("g4", GradedAudioIssue("alignment", "bad_alignment", "alignment must be a non-empty list when present"))
            alignment = []
        words = tokenize(text)
        if len(alignment) != len(words):
            fail("g4", GradedAudioIssue("alignment", "alignment_length", "alignment must cover every word exactly once"))
        prev_end: Optional[int] = None
        for pos, entry in enumerate(alignment):
            field = f"alignment[{pos}]"
            if not isinstance(entry, dict):
                fail("g4", GradedAudioIssue(field, "not_an_object", "alignment entry must be an object"))
                continue
            if pos < len(words) and _normalize_space(str(entry.get("word", ""))) != words[pos]:
                fail("g4", GradedAudioIssue(field, "word_mismatch", "alignment words must follow the text in order"))
            start = entry.get("start_ms")
            end = entry.get("end_ms")
            if (
                not isinstance(start, int)
                or isinstance(start, bool)
                or not isinstance(end, int)
                or isinstance(end, bool)
                or start < 0
                or end <= start
            ):
                fail("g4", GradedAudioIssue(field, "bad_timing", "timing must satisfy 0 <= start_ms < end_ms"))
                continue
            if prev_end is not None and start < prev_end:
                fail("g4", GradedAudioIssue(field, "non_monotonic", "alignment timings must be non-decreasing"))
            prev_end = end
    if "verified" in spec:
        fail("g5", GradedAudioIssue("verified", "verified_field_forbidden", "verified is set by the server-side gate only"))
    if not tokenize(text):
        fail("g6", GradedAudioIssue("text", "no_tokens", "text must contain at least one word"))
    return gates, issues


def _split_sentences(text: str) -> list[str]:
    parts = [part.strip() for part in _SENTENCE_SPLIT_RE.split(text.strip())]
    return [part for part in parts if part]


def assemble_graded_audio(spec: Mapping[str, Any]) -> dict[str, Any]:
    """Assemble playback data. Word timings pass through verbatim when
    alignment exists; otherwise sentences carry no timings at all."""
    text = str(spec.get("text", ""))
    sentences = _split_sentences(text)
    alignment = spec.get("alignment")
    word_timings: Optional[list[dict[str, Any]]] = None
    sentence_rows: list[dict[str, Any]] = []
    if isinstance(alignment, list) and alignment:
        word_timings = [
            {"word": entry.get("word"), "start_ms": entry.get("start_ms"), "end_ms": entry.get("end_ms")}
            for entry in alignment
            if isinstance(entry, dict)
        ]
        cursor = 0
        for sentence in sentences:
            n_tokens = len(tokenize(sentence))
            span = word_timings[cursor : cursor + n_tokens]
            cursor += n_tokens
            sentence_rows.append(
                {
                    "text": sentence,
                    "start_ms": span[0]["start_ms"] if span else None,
                    "end_ms": span[-1]["end_ms"] if span else None,
                }
            )
        highlight_level = "word"
    else:
        sentence_rows = [{"text": sentence, "start_ms": None, "end_ms": None} for sentence in sentences]
        highlight_level = "sentence"
    return {
        "id": spec.get("id"),
        "title": spec.get("title"),
        "language": spec.get("language"),
        "level": spec.get("level"),
        "text": text,
        "sentences": sentence_rows,
        "word_timings": word_timings,
        "highlight_level": highlight_level,
        "tts_text": text,
    }


__all__ = ["GradedAudioIssue", "assemble_graded_audio", "verify_graded_audio_spec"]
