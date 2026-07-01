"""oprim-068: migration_runner — run Alembic database migrations programmatically."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Literal

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from pydantic import BaseModel
from sqlalchemy import create_engine

from oprim._exceptions import OprimError


class MigrationResult(BaseModel):
    action: str
    current_revision: str | None
    message: str
    success: bool


def migration_runner(
    *,
    action: Literal["upgrade", "downgrade", "history", "current", "stamp"],
    dsn: str,
    migrations_path: Path,
    target: str = "head",
) -> MigrationResult:
    """Run Alembic database migrations programmatically.

    Args:
        action: Migration action to perform
        dsn: Database connection string
        migrations_path: Path to Alembic migrations directory (containing env.py)
        target: Migration target revision (default "head"). Use "base" for full downgrade.

    Returns:
        MigrationResult with current revision and status

    Raises:
        OprimError: Migration failed or invalid configuration

    Example:
        >>> migration_runner(
        ...     action="upgrade", dsn="postgresql://...", migrations_path=Path("migrations")
        ... )
        MigrationResult(action='upgrade', current_revision='abc123', message='OK', success=True)
    """
    cfg = Config()
    cfg.set_main_option("script_location", str(migrations_path))
    cfg.set_main_option("sqlalchemy.url", dsn)

    output_buffer = io.StringIO()
    cfg.stdout = output_buffer

    try:
        if action == "upgrade":
            command.upgrade(cfg, target)
        elif action == "downgrade":
            command.downgrade(cfg, target)
        elif action == "history":
            command.history(cfg)
        elif action == "current":
            command.current(cfg)
        elif action == "stamp":
            command.stamp(cfg, target)

        engine = create_engine(dsn)
        try:
            with engine.connect() as conn:
                context = MigrationContext.configure(conn)
                current_rev = context.get_current_revision()
        finally:
            engine.dispose()

        return MigrationResult(
            action=action,
            current_revision=current_rev,
            message="OK",
            success=True,
        )
    except Exception as e:
        raise OprimError(f"migration_runner {action} failed: {e}") from e
