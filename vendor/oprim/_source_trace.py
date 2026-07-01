"""P-G3: source_trace — atomic DB query for KU source provenance.

Async, single DB call, db_conn injected (no global state).
"""
from __future__ import annotations

import inspect
from typing import Any

from oprim._aii_graph_types import SourceTraceResult


async def source_trace(
    *,
    ku_id: str,
    db_conn: Any,
) -> SourceTraceResult:
    """Fetch source provenance for a KU via a single DB query.

    db_conn interface expected:
      fetch(sql, *args) -> list of Mapping  (async or sync)
    or
      execute_query(ku_id) -> list of Mapping  (for duck-typed mocks)
    """
    try:
        if hasattr(db_conn, "fetch"):
            sql = (
                "SELECT s.source_id, s.page, s.chunk_idx, s.text_snippet "
                "FROM ku_sources s WHERE s.ku_id = $1 ORDER BY s.source_id"
            )
            if inspect.iscoroutinefunction(db_conn.fetch):
                rows = await db_conn.fetch(sql, ku_id)
            else:
                rows = db_conn.fetch(sql, ku_id)
        elif hasattr(db_conn, "execute_query"):
            if inspect.iscoroutinefunction(db_conn.execute_query):
                rows = await db_conn.execute_query(ku_id)
            else:
                rows = db_conn.execute_query(ku_id)
        else:
            rows = []
    except Exception:
        rows = []

    source_ids: list[str] = []
    positions: list[dict] = []
    for row in rows:
        r = dict(row) if not isinstance(row, dict) else row
        sid = r.get("source_id", "")
        if sid and sid not in source_ids:
            source_ids.append(sid)
        positions.append({
            "source_id": sid,
            "page": r.get("page"),
            "chunk_idx": r.get("chunk_idx"),
            "text_snippet": r.get("text_snippet", ""),
        })

    return SourceTraceResult(
        ku_id=ku_id,
        source_ids=source_ids,
        source_positions=positions,
        trace_depth=len(positions),
    )
