"""Auto-split from hicode whl."""

from __future__ import annotations
import difflib
import re
from dataclasses import dataclass
from pathlib import Path
from ._exceptions import ParseOprimError

@dataclass
class Hunk:
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    header: str
    lines: list[str]

@dataclass
class FileDiff:
    old_path: str
    new_path: str
    hunks: list[Hunk]

def parse_unified_diff(diff_text: str) -> list[FileDiff]:
    """解析 unified diff 文本为结构化表示。

    Args:
        diff_text: unified diff 字符串（git diff / diff -u 输出）。

    Returns:
        FileDiff 列表，每项含 old_path / new_path / hunks。

    Raises:
        ParseOprimError: diff 格式严重错误。

    Example:
        >>> diffs = parse_unified_diff(git_diff_output)
        >>> diffs[0].hunks[0].old_start
        10
    """
    if not diff_text.strip():
        return []

    file_diffs: list[FileDiff] = []
    current_file: FileDiff | None = None
    current_hunk: Hunk | None = None

    hunk_re = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)")

    for line in diff_text.splitlines(keepends=True):
        stripped = line.rstrip("\n")

        if stripped.startswith("--- "):
            if current_hunk and current_file:
                current_file.hunks.append(current_hunk)
                current_hunk = None
            old_path = stripped[4:].split("\t")[0]
            old_path = old_path[2:] if old_path.startswith("a/") else old_path
            current_file = FileDiff(old_path=old_path, new_path="", hunks=[])

        elif stripped.startswith("+++ ") and current_file:
            new_path = stripped[4:].split("\t")[0]
            new_path = new_path[2:] if new_path.startswith("b/") else new_path
            current_file.new_path = new_path
            file_diffs.append(current_file)

        elif m := hunk_re.match(stripped):
            if current_hunk and current_file:
                current_file.hunks.append(current_hunk)
            current_hunk = Hunk(
                old_start=int(m.group(1)),
                old_count=int(m.group(2) or 1),
                new_start=int(m.group(3)),
                new_count=int(m.group(4) or 1),
                header=m.group(5).strip(),
                lines=[],
            )

        elif current_hunk is not None and stripped.startswith(("+", "-", " ")):
            current_hunk.lines.append(stripped)

    # 收尾
    if current_hunk and current_file:
        current_file.hunks.append(current_hunk)

    return file_diffs
