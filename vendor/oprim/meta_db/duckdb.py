"""DuckDB-backed metadata store with migration support."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import duckdb

from oprim._logging import log as olog
from oprim.errors import MetaDBError


class MetaDB:
    """Thin wrapper around a DuckDB connection with migration support."""

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._conn: duckdb.DuckDBPyConnection | None = None

    def connect(self) -> duckdb.DuckDBPyConnection:
        if self._conn is None:
            try:
                self._conn = duckdb.connect(str(self._path))
            except Exception as e:
                raise MetaDBError(
                    f"Cannot connect to DuckDB at {self._path}: {e}"
                ) from e
        return self._conn

    def execute(self, sql: str, params: list[Any] | None = None):
        conn = self.connect()
        try:
            if params:
                return conn.execute(sql, params)
            return conn.execute(sql)
        except Exception as e:
            olog.error("meta_db execute failed", sql=sql[:100], error=str(e))
            raise MetaDBError(f"Execute failed: {e}") from e

    def fetchall(self, sql: str, params: list[Any] | None = None) -> list[tuple]:
        result = self.execute(sql, params)
        return result.fetchall()

    def migrate(self, migrations_dir: Path) -> None:
        """Apply pending SQL migration files in lexicographic order."""
        migrations_dir = Path(migrations_dir)
        conn = self.connect()
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS _migrations (
                filename TEXT PRIMARY KEY,
                applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        applied = {
            r[0] for r in conn.execute("SELECT filename FROM _migrations").fetchall()
        }
        sql_files = sorted(migrations_dir.glob("*.sql"))
        for f in sql_files:
            if f.name not in applied:
                try:
                    sql = f.read_text()
                    # DuckDB does not have executescript; split on ";"
                    for stmt in sql.split(";"):
                        stmt = stmt.strip()
                        if stmt:
                            conn.execute(stmt)
                    conn.execute(
                        "INSERT INTO _migrations (filename) VALUES (?)", [f.name]
                    )
                    olog.info("migration applied", file=f.name)
                except Exception as e:
                    raise MetaDBError(f"Migration {f.name} failed: {e}") from e

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None


def open_meta_db(path: Path) -> MetaDB:
    """Open a MetaDB at *path* (creates the file if it does not exist)."""
    return MetaDB(path)
