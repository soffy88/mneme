"""oprim.subject_create — Create and persist a Subject record."""
from __future__ import annotations
from typing import Any
from oprim._hevi_types import Subject


async def subject_create(subject: Subject, *, dsn: str | None = None, store: Any = None) -> Subject:
    """Create and persist a Subject record via obase.persistence.

    Args:
        subject: The Subject instance to persist.
        dsn: Database DSN. If provided, persists to DB via obase.persistence.
        store: Optional dict for testing (overrides dsn).

    Returns:
        The persisted Subject (same object).

    Raises:
        OprimError: If persistence fails.

    Example:
        >>> subj = await subject_create(subject, dsn=config.db_dsn)
    """
    if store is not None:
        store[subject.subject_id] = subject
        return subject

    if dsn is not None:
        from obase.persistence import write_one
        await write_one(
            dsn=dsn,
            table="subjects",
            data=subject.model_dump(),
            conflict_columns=["subject_id"],
            on_conflict="do_nothing",
        )
        return subject

    # 无 dsn 无 store：明确报错，不静默降级内存
    raise RuntimeError(
        "subject_create requires dsn= or store= parameter. "
        "Pass dsn=config.db_dsn to persist to database."
    )
