"""Read-only Alembic preflight helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True, slots=True)
class MigrationPreflight:
    current_revision: str | None
    expected_heads: tuple[str, ...]
    pending: bool
    multiple_heads: bool
    downgrade_available: bool
    issues: tuple[str, ...] = ()

    @property
    def safe(self) -> bool:
        return not self.issues and not self.pending and not self.multiple_heads


def build_migration_preflight(*, current_revision: str | None, expected_heads: Iterable[str], discovered_heads: Iterable[str], downgrade_available: bool) -> MigrationPreflight:
    expected = tuple(sorted(set(expected_heads)))
    discovered = tuple(sorted(set(discovered_heads)))
    issues: list[str] = []
    if len(discovered) != 1:
        issues.append("migration heads are not unique")
    if expected and discovered != expected:
        issues.append("discovered heads differ from expected head")
    pending = current_revision not in {None, *expected}
    if current_revision is None:
        issues.append("current database revision is unknown")
    elif pending:
        issues.append("database has pending migrations")
    return MigrationPreflight(current_revision=current_revision, expected_heads=expected, pending=pending, multiple_heads=len(discovered) != 1, downgrade_available=downgrade_available, issues=tuple(issues))


def migration_files_have_downgrades(directory: Path) -> bool:
    files = list(directory.glob("*.py"))
    return bool(files) and all("def downgrade" in path.read_text(encoding="utf-8") for path in files if path.name != "__init__.py")


__all__ = ["MigrationPreflight", "build_migration_preflight", "migration_files_have_downgrades"]
