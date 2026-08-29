"""Clean-room SRT/VTT parsers for Immersive Learning MVP."""

from __future__ import annotations

import re
from dataclasses import dataclass


class TranscriptParseError(ValueError):
    """Malformed subtitle rejection."""


@dataclass(frozen=True, slots=True)
class ParsedCue:
    order_index: int
    start_ms: int
    end_ms: int
    text: str


_TIME_TOKEN = re.compile(
    r"(?:(\d{1,2}):)?(\d{1,2}):(\d{1,2})[.,](\d{1,3})"
)
_HTML_TAG = re.compile(r"<[^>]+>")
_SCRIPT_BLOCK = re.compile(r"<script\b[^>]*>.*?</script>", re.IGNORECASE | re.DOTALL)
_VTT_NOTE = re.compile(r"^(NOTE|STYLE|REGION)\b", re.IGNORECASE)


def _parse_timestamp(token: str) -> int:
    match = _TIME_TOKEN.fullmatch(token.strip())
    if match is None:
        raise TranscriptParseError(f"invalid timestamp: {token!r}")
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2))
    seconds = int(match.group(3))
    fraction = match.group(4).ljust(3, "0")[:3]
    millis = int(fraction)
    return ((hours * 60 + minutes) * 60 + seconds) * 1000 + millis


def _strip_markup(text: str) -> str:
    cleaned = _SCRIPT_BLOCK.sub("", text)
    cleaned = _HTML_TAG.sub("", cleaned)
    cleaned = cleaned.replace("&nbsp;", " ").replace("&amp;", "&")
    cleaned = cleaned.replace("&lt;", "<").replace("&gt;", ">")
    return " ".join(cleaned.split()).strip()


def _validate_cues(cues: list[ParsedCue]) -> list[ParsedCue]:
    if not cues:
        raise TranscriptParseError("empty transcript")
    previous_end = -1
    for cue in cues:
        if cue.start_ms < 0:
            raise TranscriptParseError("start_ms must be >= 0")
        if cue.end_ms <= cue.start_ms:
            raise TranscriptParseError("end_ms must be > start_ms")
        if cue.end_ms - cue.start_ms > 10 * 60 * 1000:
            raise TranscriptParseError("cue duration exceeds sanity limit")
        if cue.start_ms < previous_end - 5_000:
            # Allow slight overlap but reject severe disorder.
            raise TranscriptParseError("cues are not ordered")
        if not cue.text:
            raise TranscriptParseError("empty cue text")
        previous_end = cue.end_ms
    return cues


def parse_srt(content: str) -> list[ParsedCue]:
    blocks = re.split(r"\n\s*\n", content.replace("\r\n", "\n").replace("\r", "\n").strip())
    cues: list[ParsedCue] = []
    for block in blocks:
        lines = [line for line in block.split("\n") if line.strip() != ""]
        if not lines:
            continue
        # Optional numeric index line.
        if re.fullmatch(r"\d+", lines[0].strip()) and len(lines) >= 2:
            lines = lines[1:]
        if not lines:
            continue
        arrow = lines[0]
        if "-->" not in arrow:
            raise TranscriptParseError("missing SRT timing arrow")
        left, right = [part.strip() for part in arrow.split("-->", 1)]
        right = right.split(" ", 1)[0]
        text = _strip_markup(" ".join(lines[1:]))
        cues.append(
            ParsedCue(
                order_index=len(cues),
                start_ms=_parse_timestamp(left),
                end_ms=_parse_timestamp(right),
                text=text,
            )
        )
    return _validate_cues(cues)


def parse_vtt(content: str) -> list[ParsedCue]:
    text = content.replace("\r\n", "\n").replace("\r", "\n")
    if text.lstrip().startswith("\ufeff"):
        text = text.lstrip("\ufeff")
    lines = text.split("\n")
    if not lines or not lines[0].strip().upper().startswith("WEBVTT"):
        # Be tolerant if WEBVTT header missing but content looks like VTT cues.
        pass
    body = "\n".join(lines[1:] if lines and lines[0].strip().upper().startswith("WEBVTT") else lines)
    blocks = re.split(r"\n\s*\n", body.strip())
    cues: list[ParsedCue] = []
    for block in blocks:
        raw_lines = [line for line in block.split("\n") if line.strip() != ""]
        if not raw_lines:
            continue
        if _VTT_NOTE.match(raw_lines[0]):
            continue
        if "-->" not in raw_lines[0] and len(raw_lines) >= 2 and "-->" in raw_lines[1]:
            raw_lines = raw_lines[1:]
        if "-->" not in raw_lines[0]:
            continue
        left, right = [part.strip() for part in raw_lines[0].split("-->", 1)]
        right = right.split(" ", 1)[0]
        cue_text = _strip_markup(" ".join(raw_lines[1:]))
        cues.append(
            ParsedCue(
                order_index=len(cues),
                start_ms=_parse_timestamp(left),
                end_ms=_parse_timestamp(right),
                text=cue_text,
            )
        )
    return _validate_cues(cues)


def parse_subtitle(content: str, *, format_hint: str | None = None) -> tuple[str, list[ParsedCue]]:
    hint = (format_hint or "").lower().lstrip(".")
    stripped = content.lstrip("\ufeff").lstrip()
    if hint == "vtt" or stripped.upper().startswith("WEBVTT"):
        return "vtt", parse_vtt(content)
    if hint == "srt":
        return "srt", parse_srt(content)
    # Heuristic fallback.
    if "-->" in content and re.search(r"\d{2}:\d{2}:\d{2}[.,]\d", content):
        try:
            return "srt", parse_srt(content)
        except TranscriptParseError:
            return "vtt", parse_vtt(content)
    raise TranscriptParseError("unsupported or malformed subtitle")


def align_by_timing(
    primary: list[ParsedCue],
    translation: list[ParsedCue],
    *,
    max_skew_ms: int = 400,
) -> list[str | None]:
    """Align translation texts onto primary cues by start time.

    Returns one translated_text per primary cue. Unaligned slots are None.
    Does not invent high-confidence alignments when skew is large.
    """

    if not translation:
        return [None] * len(primary)
    result: list[str | None] = []
    j = 0
    for cue in primary:
        best: str | None = None
        best_skew = max_skew_ms + 1
        while j < len(translation) and translation[j].start_ms < cue.start_ms - max_skew_ms:
            j += 1
        for k in range(j, min(j + 3, len(translation))):
            skew = abs(translation[k].start_ms - cue.start_ms)
            if skew < best_skew:
                best_skew = skew
                best = translation[k].text
        result.append(best if best_skew <= max_skew_ms else None)
    return result
