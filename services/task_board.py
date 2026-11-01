"""Study task board + derived calendar (DeepTutor method, clean rewrite).

Tasks are plain student-owned rows: move only changes status/position,
archive/restore only flips the archived flag. The calendar is a read-only
derived view merging task due dates with FSRS review dues; it creates
no schedule of its own.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Mapping, Optional

TASK_STATUSES = ("todo", "in_progress", "done")

MAX_TITLE_CHARS = 200
MAX_NOTES_CHARS = 2000
MAX_POSITION = 100000


class TaskIssue:
    def __init__(self, field: str, code: str, message: str) -> None:
        self.field = field
        self.code = code
        self.message = message

    def to_dict(self) -> dict[str, str]:
        return {"field": self.field, "code": self.code, "message": self.message}


def validate_task_payload(data: Mapping[str, Any]) -> list[TaskIssue]:
    """Validate a create/update payload. Update callers merge first."""
    issues: list[TaskIssue] = []
    title = data.get("title")
    if not isinstance(title, str) or not title.strip():
        issues.append(TaskIssue("title", "empty_title", "title must be a non-empty string"))
    elif len(title) > MAX_TITLE_CHARS:
        issues.append(TaskIssue("title", "title_too_long", "title too long"))
    notes = data.get("notes", "")
    if notes is not None and (not isinstance(notes, str) or len(notes) > MAX_NOTES_CHARS):
        issues.append(TaskIssue("notes", "bad_notes", "notes must be a string of at most 2000 chars"))
    status = data.get("status", "todo")
    if status not in TASK_STATUSES:
        issues.append(TaskIssue("status", "bad_status", "status must be todo, in_progress, or done"))
    due = data.get("due_date")
    if due is not None:
        if not isinstance(due, str):
            issues.append(TaskIssue("due_date", "bad_due_date", "due_date must be an ISO date string"))
        else:
            try:
                date.fromisoformat(due)
            except ValueError:
                issues.append(TaskIssue("due_date", "bad_due_date", "due_date must be an ISO date string"))
    position = data.get("position", 0)
    if not isinstance(position, int) or isinstance(position, bool) or not 0 <= position <= MAX_POSITION:
        issues.append(TaskIssue("position", "bad_position", "position must be an integer in range"))
    return issues


def apply_move(
    task: Mapping[str, Any],
    *,
    status: Optional[str] = None,
    position: Optional[int] = None,
) -> tuple[dict[str, Any], list[TaskIssue]]:
    """Move only touches status/position; everything else is copied as-is."""
    issues: list[TaskIssue] = []
    updated = dict(task)
    if status is not None:
        if status not in TASK_STATUSES:
            issues.append(TaskIssue("status", "bad_status", "status must be todo, in_progress, or done"))
        else:
            updated["status"] = status
    if position is not None:
        if not isinstance(position, int) or isinstance(position, bool) or not 0 <= position <= MAX_POSITION:
            issues.append(TaskIssue("position", "bad_position", "position must be an integer in range"))
        else:
            updated["position"] = position
    return updated, issues


def sort_tasks(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Board order: position, then creation time. Archived rows sort last."""
    def key(item: dict[str, Any]) -> tuple:
        created = item.get("created_at") or ""
        return (bool(item.get("archived")), int(item.get("position", 0)), str(created))

    return sorted(tasks, key=key)


def build_calendar(
    tasks: list[Mapping[str, Any]],
    reviews: list[Mapping[str, Any]],
    start: date,
    end: date,
) -> list[dict[str, Any]]:
    """Merge task dues + FSRS dues into per-day entries. Read-only view."""
    by_day: dict[str, list[dict[str, Any]]] = {}
    for task in tasks:
        due = task.get("due_date")
        if due is None:
            continue
        day = due if isinstance(due, str) else str(due)
        try:
            day_date = date.fromisoformat(day)
        except ValueError:
            continue
        if not start <= day_date <= end:
            continue
        by_day.setdefault(day, []).append(
            {
                "kind": "task",
                "id": str(task.get("id")),
                "title": task.get("title"),
                "status": task.get("status"),
                "archived": bool(task.get("archived")),
            }
        )
    for review in reviews:
        due = review.get("fsrs_due")
        if due is None:
            continue
        if isinstance(due, datetime):
            day_date = due.date()
        elif isinstance(due, str):
            try:
                day_date = datetime.fromisoformat(due.replace("Z", "+00:00")).date()
            except ValueError:
                continue
        else:
            continue
        if not start <= day_date <= end:
            continue
        by_day.setdefault(day_date.isoformat(), []).append(
            {
                "kind": "review",
                "wrong_question_id": str(review.get("wrong_question_id")),
                "subject": review.get("subject"),
            }
        )
    return [{"date": day, "entries": by_day[day]} for day in sorted(by_day)]


__all__ = [
    "MAX_NOTES_CHARS",
    "MAX_POSITION",
    "MAX_TITLE_CHARS",
    "TASK_STATUSES",
    "TaskIssue",
    "apply_move",
    "build_calendar",
    "sort_tasks",
    "validate_task_payload",
]
