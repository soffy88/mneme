from __future__ import annotations

import re
from datetime import date
from typing import Any

from pydantic import BaseModel, Field

from oprim._exceptions import OprimError


class ObsidianTask(BaseModel):
    """Obsidian 任务结构."""

    text: str
    completed: bool
    due_date: date | None = None
    scheduled_date: date | None = None
    tags: list[str] = Field(default_factory=list)
    raw_line: str
    line_number: int


# Regex patterns
TASK_LINE_RE = re.compile(r"^\s*-\s+\[(.)\]\s+(.*)$")
DUE_RE = re.compile(r"(?:📅|due:)\s*(\d{4}-\d{2}-\d{2})")
SCHED_RE = re.compile(r"(?:⏳|scheduled:)\s*(\d{4}-\d{2}-\d{2})")
TAGS_RE = re.compile(r"#([\w/-]+)")


def _parse_date(date_str: str) -> date | None:
    try:
        return date.fromisoformat(date_str)
    except ValueError:
        return None


def parse_obsidian_tasks(*, content: str | None = None) -> list[ObsidianTask]:
    """解析 Obsidian Markdown 中的任务列表.

    Args:
        content: Markdown 内容字符串

    Returns:
        解析后的任务对象列表

    Raises:
        OprimError: 如果 content 为 None

    Example:
        ```python
        content = "- [ ] Buy milk 📅 2024-05-20 #errand"
        tasks = parse_obsidian_tasks(content=content)
        assert tasks[0].text == "Buy milk"
        assert tasks[0].completed is False
        assert str(tasks[0].due_date) == "2024-05-20"
        ```
    """
    if content is None:
        raise OprimError("Content cannot be None")

    tasks = []
    lines = content.split("\n")

    for i, line in enumerate(lines):
        match = TASK_LINE_RE.match(line)
        if not match:
            continue

        status_char = match.group(1)
        raw_text = match.group(2).strip()
        if not raw_text:
            continue

        completed = status_char.lower() == "x"

        due_date = None
        due_match = DUE_RE.search(raw_text)
        if due_match:
            due_date = _parse_date(due_match.group(1))
            raw_text = DUE_RE.sub("", raw_text).strip()

        scheduled_date = None
        sched_match = SCHED_RE.search(raw_text)
        if sched_match:
            scheduled_date = _parse_date(sched_match.group(1))
            raw_text = SCHED_RE.sub("", raw_text).strip()

        tags = []
        for tag_match in TAGS_RE.finditer(raw_text):
            tags.append(tag_match.group(1))
        
        # Clean text
        text = TAGS_RE.sub("", raw_text).strip()
        # Remove extra whitespace
        text = re.sub(r"\s+", " ", text)

        tasks.append(
            ObsidianTask(
                text=text,
                completed=completed,
                due_date=due_date,
                scheduled_date=scheduled_date,
                tags=tags,
                raw_line=line,
                line_number=i + 1,
            )
        )

    return tasks
