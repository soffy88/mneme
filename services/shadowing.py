"""Shadowing practice loop (Parroto method, clean rewrite).

Listen, repeat, get scored. Scoring surfaces ONLY the dimensions the
real pronunciation contract returns (overall / fluency / accuracy /
word scores) plus a deterministic STT-transcript diff. There is no
intonation or rhythm dimension in the contract, so none is reported.
Audio is never stored: only scores, the transcript, and weak words
are persisted.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping, Optional

from services.dictation import diff_words, tokenize

MAX_SENTENCES = 20
WEAK_WORD_THRESHOLD = 0.6


class ShadowingIssue:
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


def verify_shadowing_spec(spec: Mapping[str, Any]) -> tuple[dict[str, bool], list[ShadowingIssue]]:
    """Five gates."""
    gates: dict[str, bool] = {f"g{i}": True for i in range(1, 6)}
    issues: list[ShadowingIssue] = []

    def fail(gate: str, issue: ShadowingIssue) -> None:
        gates[gate] = False
        issues.append(issue)

    if not isinstance(spec, dict):
        return gates, [ShadowingIssue("", "not_an_object", "spec must be an object")]
    spec_id = spec.get("id")
    if not isinstance(spec_id, str) or not spec_id or len(spec_id) > 100:
        fail("g1", ShadowingIssue("id", "bad_id", "id must be a non-empty string of at most 100 chars"))
    if not _is_bilingual(spec.get("title")):
        fail("g2", ShadowingIssue("title", "bad_title", "title must carry non-empty zh and en"))
    if spec.get("language") not in ("zh", "en"):
        fail("g2", ShadowingIssue("language", "bad_language", "language must be zh or en"))
    level = spec.get("level")
    if not isinstance(level, int) or isinstance(level, bool) or not 1 <= level <= 5:
        fail("g2", ShadowingIssue("level", "bad_level", "level must be an integer from 1 to 5"))
    sentences = spec.get("target_sentences")
    if not isinstance(sentences, list) or not sentences:
        fail("g3", ShadowingIssue("target_sentences", "missing_sentences", "target_sentences must be a non-empty list"))
        sentences = []
    if len(sentences) > MAX_SENTENCES:
        fail("g3", ShadowingIssue("target_sentences", "too_many_sentences", "too many sentences"))
    for pos, sentence in enumerate(sentences):
        if not isinstance(sentence, str) or not sentence.strip():
            fail("g3", ShadowingIssue(f"target_sentences[{pos}]", "empty_sentence", "sentence must be non-empty"))
    if "verified" in spec:
        fail("g4", ShadowingIssue("verified", "verified_field_forbidden", "verified is set by the server-side gate only"))
    if not tokenize(" ".join(s for s in sentences if isinstance(s, str))):
        fail("g5", ShadowingIssue("target_sentences", "no_tokens", "sentences must contain at least one word"))
    return gates, issues


def _contract_scores(raw: object) -> dict[str, Any]:
    """Extract ONLY the fields the pronunciation contract returns."""
    if raw is None:
        return {"overall_score": None, "fluency_score": None, "accuracy_score": None, "word_scores": []}
    if isinstance(raw, dict):
        data = raw
    else:
        data = {
            "overall_score": getattr(raw, "overall_score", None),
            "fluency_score": getattr(raw, "fluency_score", None),
            "accuracy_score": getattr(raw, "accuracy_score", None),
            "word_scores": getattr(raw, "word_scores", []),
        }
    word_scores: list[dict[str, Any]] = []
    for entry in data.get("word_scores") or []:
        if not isinstance(entry, dict):
            continue
        word_scores.append(
            {
                "word": entry.get("word"),
                "score": entry.get("score"),
                "issue": entry.get("issue"),
            }
        )
    return {
        "overall_score": data.get("overall_score"),
        "fluency_score": data.get("fluency_score"),
        "accuracy_score": data.get("accuracy_score"),
        "word_scores": word_scores,
    }


def _weak_words(scores: Mapping[str, Any], diff: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deterministic weak-word rules: low word scores + transcript gaps."""
    weak: dict[str, dict[str, Any]] = {}
    for entry in scores.get("word_scores", []):
        score = entry.get("score")
        word = entry.get("word")
        if isinstance(word, str) and isinstance(score, (int, float)) and score < WEAK_WORD_THRESHOLD:
            weak[word] = {"word": word, "score": score, "source": "pronunciation"}
    for item in diff:
        if item["status"] in ("missing", "wrong"):
            word = item["word"]
            if word not in weak:
                weak[word] = {"word": word, "score": None, "source": "transcript"}
    return [weak[key] for key in sorted(weak)]


async def score_shadowing(
    audio_b64: str,
    reference_text: str,
    *,
    pron_fn: Optional[Callable[..., Any]] = None,
    stt_fn: Optional[Callable[..., Any]] = None,
) -> dict[str, Any]:
    """Score one utterance. Callables are injectable for tests; the
    defaults are the existing wrap_pron / wrap_stt services."""
    if not isinstance(audio_b64, str) or not audio_b64:
        raise ValueError("audio_b64 must be a non-empty string")
    if not isinstance(reference_text, str) or not reference_text.strip():
        raise ValueError("reference_text must be a non-empty string")
    pron = pron_fn or _default_pron
    stt = stt_fn or _default_stt
    raw = await pron(audio_b64, reference_text)
    scores = _contract_scores(raw)
    transcript = await stt(audio_b64)
    if not isinstance(transcript, str):
        transcript = str(transcript)
    diff = diff_words(tokenize(reference_text), tokenize(transcript))
    return {
        "scores": scores,
        "transcript": transcript,
        "diff": diff,
        "weak_words": _weak_words(scores, diff),
    }


async def _default_pron(audio_b64: str, reference_text: str) -> Any:
    from services.speaking_service import wrap_pron

    return await wrap_pron(audio_b64, reference_text)


async def _default_stt(audio_b64: str) -> str:
    from services.speaking_service import wrap_stt

    return await wrap_stt(audio_b64)


__all__ = [
    "MAX_SENTENCES",
    "ShadowingIssue",
    "WEAK_WORD_THRESHOLD",
    "score_shadowing",
    "verify_shadowing_spec",
]
