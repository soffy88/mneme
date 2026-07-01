"""oprim.srt_translate — SRT subtitle translation via LLMCaller Protocol.

Example:
    >>> import asyncio
    >>> from pathlib import Path
    >>> from oprim.srt_translate import srt_translate
    >>> result = asyncio.run(srt_translate(
    ...     src_srt_path=Path("zh.srt"), target_lang="en",
    ...     llm=my_llm_caller, output_path=Path("en.srt"),
    ... ))

Raises:
    SRTTranslateError: Translation failed.
    SRTParseError: SRT format invalid.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Protocol, runtime_checkable


class SRTTranslateError(Exception):
    """SRT translation failed."""


class SRTParseError(SRTTranslateError):
    """SRT file format is invalid."""


@runtime_checkable
class LLMCaller(Protocol):
    """Protocol for LLM invocation."""

    async def __call__(self, *, prompt: str) -> str: ...


async def srt_translate(
    *,
    src_srt_path: Path,
    target_lang: str,
    llm: LLMCaller,
    output_path: Path,
    batch_size: int = 20,
) -> Path:
    """Translate SRT subtitles while preserving timestamps.

    Args:
        src_srt_path: Source SRT file.
        target_lang: Target language code (e.g. 'en', 'ja').
        llm: LLMCaller protocol instance for translation.
        output_path: Destination SRT file.
        batch_size: Number of subtitle entries per LLM batch call.

    Returns:
        The output_path on success.

    Raises:
        SRTParseError: Source SRT is malformed or empty.
        SRTTranslateError: LLM translation failed or count mismatch.

    Example:
        >>> await srt_translate(
        ...     src_srt_path=Path("zh.srt"), target_lang="en",
        ...     llm=llm_caller, output_path=Path("en.srt"),
        ... )
    """
    if not src_srt_path.exists():
        raise SRTParseError(f"SRT file not found: {src_srt_path}")

    entries = _parse_srt(src_srt_path)
    if not entries:
        raise SRTParseError("SRT file is empty or has no valid entries")

    translated_texts: list[str] = []
    for i in range(0, len(entries), batch_size):
        batch = entries[i : i + batch_size]
        texts = [e["text"] for e in batch]
        prompt = (
            f"Translate the following {len(texts)} subtitle lines to {target_lang}. "
            f"Return exactly {len(texts)} lines, one translation per line, no numbering.\n\n"
            + "\n".join(texts)
        )
        response = await llm(prompt=prompt)
        lines = [ln.strip() for ln in response.strip().split("\n") if ln.strip()]
        if len(lines) != len(texts):
            raise SRTTranslateError(
                f"LLM returned {len(lines)} lines, expected {len(texts)}"
            )
        translated_texts.extend(lines)

    # Write output SRT
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        for idx, entry in enumerate(entries):
            f.write(f"{idx + 1}\n")
            f.write(f"{entry['timestamp']}\n")
            f.write(f"{translated_texts[idx]}\n\n")

    return output_path


_SRT_TIMESTAMP_RE = re.compile(
    r"\d{2}:\d{2}:\d{2},\d{3}\s*-->\s*\d{2}:\d{2}:\d{2},\d{3}"
)


def _parse_srt(path: Path) -> list[dict[str, str]]:
    """Parse SRT file into list of {timestamp, text} dicts."""
    content = path.read_text(encoding="utf-8")
    blocks = re.split(r"\n\s*\n", content.strip())
    entries: list[dict[str, str]] = []

    for block in blocks:
        lines = block.strip().split("\n")
        if len(lines) < 3:
            continue
        # Line 0 = index, Line 1 = timestamp, Line 2+ = text
        timestamp_line = lines[1].strip()
        if not _SRT_TIMESTAMP_RE.match(timestamp_line):
            raise SRTParseError(f"Invalid timestamp: {timestamp_line}")
        text = " ".join(ln.strip() for ln in lines[2:])
        entries.append({"timestamp": timestamp_line, "text": text})

    return entries
