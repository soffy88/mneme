"""LRC timestamp parser.

Source format (iChochy/NCE):
    [al:新概念英语第一册]
    [ar:New Concept English]
    [00:00.61]Lesson 1 | 第1课
    [00:02.71]Excuse me! | 打扰一下！

- Timestamps: [mm:ss.xx] with 2- or 3-digit fractions (xx -> .xx s, xxx -> .xxx s).
- Bilingual lines split on the first '|' into english / chinese.
- English-only lines are valid (chinese_text = None).
- Comments (#...), empty lines and metadata tags ([al:]/[ar:]/[ti:]/[by:]) are skipped.
- Lines with seconds >= 60 are invalid and skipped (mirrors upstream LRCParser).
"""

import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

LYRIC_TIME_RE = re.compile(r"^\[(\d{1,3}):(\d{2})\.(\d{2,3})\](.*)")


@dataclass
class LRCLine:
    start_ms: int
    english_text: str
    chinese_text: Optional[str]
    raw_text: str
    source_line: int


@dataclass
class LRCParseResult:
    lines: List[LRCLine]
    skipped_meta: int = 0
    skipped_empty: int = 0
    skipped_invalid: int = 0
    skipped_duplicates: int = 0


def parse_lrc(lrc_text: str) -> LRCParseResult:
    lines: List[LRCLLine] = []
    skipped_meta = 0
    skipped_empty = 0
    skipped_invalid = 0
    skipped_duplicates = 0
    seen_raw: set = set()

    for idx, raw in enumerate(lrc_text.split("\n"), start=1):
        stripped = raw.strip()
        if not stripped:
            skipped_empty += 1
            continue
        if stripped.startswith("#"):
            skipped_empty += 1
            continue
        if stripped.startswith("[") and not stripped[1:2].isdigit():
            skipped_meta += 1
            continue

        match = LYRIC_TIME_RE.match(stripped)
        if not match:
            skipped_invalid += 1
            continue

        minutes = int(match.group(1))
        seconds = int(match.group(2))
        if seconds >= 60:
            skipped_invalid += 1
            continue

        fraction = float("0." + match.group(3))
        start_ms = round((minutes * 60 + seconds + fraction) * 1000)

        body = match.group(4).strip()
        if not body:
            skipped_invalid += 1
            continue

        # Exact duplicate source line (same timestamp + same text): the source
        # carries no additional information; keep the first occurrence so the
        # (lesson_id, source_entry_key) natural key stays unique.
        if stripped in seen_raw:
            skipped_duplicates += 1
            continue
        seen_raw.add(stripped)

        english, _, chinese = body.partition("|")
        english = english.strip()
        chinese = chinese.strip() or None
        if not english:
            skipped_invalid += 1
            continue

        lines.append(
            LRCLine(
                start_ms=start_ms,
                english_text=english,
                chinese_text=chinese,
                raw_text=stripped,
                source_line=idx,
            )
        )

    lines.sort(key=lambda l: l.start_ms)
    return LRCParseResult(
        lines=lines,
        skipped_meta=skipped_meta,
        skipped_empty=skipped_empty,
        skipped_invalid=skipped_invalid,
        skipped_duplicates=skipped_duplicates,
    )


def check_timestamp_order(lines: List[LRCLine]) -> List[Tuple[int, int]]:
    """Return index pairs (i, i+1) where start_ms decreases (violations)."""
    violations: List[Tuple[int, int]] = []
    for i in range(len(lines) - 1):
        if lines[i + 1].start_ms < lines[i].start_ms:
            violations.append((i, i + 1))
    return violations
