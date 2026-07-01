"""PostgreSQL oprim — 5 atomic PostgreSQL inspection operations."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from oprim._exceptions import (
    OprimAuthError,
    OprimConnectionError,
    OprimError,
    OprimTimeoutError,
)

try:
    import psycopg
except ImportError:
    psycopg = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class PoolStatus(BaseModel):
    total_connections: int
    active_connections: int
    idle_connections: int
    idle_in_transaction: int
    waiting_connections: int
    max_connections: int
    usage_percent: float


class SlowQuery(BaseModel):
    query_id: int
    query_text: str
    calls: int
    total_time_ms: float
    mean_time_ms: float
    max_time_ms: float
    rows: int


class LockInfo(BaseModel):
    locktype: str
    relation_name: str | None
    mode: str
    granted: bool
    pid: int
    query: str | None
    wait_event_type: str | None
    wait_duration_sec: float | None


class TableSize(BaseModel):
    schema_name: str
    table_name: str
    total_bytes: int
    table_bytes: int
    indexes_bytes: int
    toast_bytes: int
    row_count_estimate: int


class ReplicationLag(BaseModel):
    is_primary: bool
    replicas: list[dict[str, Any]]
    max_lag_seconds: float | None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _connect(dsn: str, timeout_sec: int) -> Any:
    """Return a psycopg connection; raise oprim-typed errors on failure."""
    if psycopg is None:
        raise OprimError(
            "psycopg is required for postgres oprim. Install with: pip install 'psycopg[binary]'"
        )

    try:
        return psycopg.connect(dsn, connect_timeout=timeout_sec)
    except psycopg.OperationalError as exc:
        msg = str(exc).lower()
        if "password" in msg or "authentication" in msg or "pg_hba" in msg:
            raise OprimAuthError(f"PostgreSQL authentication failed: {exc}") from exc
        raise OprimConnectionError(f"Cannot connect to PostgreSQL: {exc}") from exc
    except TimeoutError as exc:
        raise OprimTimeoutError(f"PostgreSQL connection timed out: {exc}") from exc
    except Exception as exc:
        raise OprimConnectionError(f"Unexpected PostgreSQL connection error: {exc}") from exc


# ---------------------------------------------------------------------------
# 3.2 postgres_pool_status
# ---------------------------------------------------------------------------


def postgres_pool_status(
    *,
    dsn: str,
    timeout_sec: int = 5,
) -> PoolStatus:
    """查 PostgreSQL 连接池状态.

    Args:
        dsn: PostgreSQL connection string (postgresql://user:pass@host:5432/dbname)
        timeout_sec: 连接超时秒数

    Returns:
        PoolStatus 含连接数 / 状态分布 / 使用率

    Raises:
        OprimConnectionError / OprimTimeoutError / OprimAuthError
    """
    conn = _connect(dsn, timeout_sec)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT state, COUNT(*) FROM pg_stat_activity GROUP BY state;")
            rows = cur.fetchall()
            state_counts: dict[str, int] = {}
            for state, count in rows:
                state_counts[state or "unknown"] = int(count)

            cur.execute("SHOW max_connections;")
            max_conn_row = cur.fetchone()
            max_connections = int(max_conn_row[0]) if max_conn_row else 0

            cur.execute("SELECT COUNT(*) FROM pg_stat_activity WHERE wait_event_type = 'Lock';")
            wait_row = cur.fetchone()
            waiting = int(wait_row[0]) if wait_row else 0
    finally:
        conn.close()

    active = state_counts.get("active", 0)
    idle = state_counts.get("idle", 0)
    idle_tx = state_counts.get("idle in transaction", 0)
    total = sum(state_counts.values())
    usage = (total / max_connections * 100.0) if max_connections > 0 else 0.0

    return PoolStatus(
        total_connections=total,
        active_connections=active,
        idle_connections=idle,
        idle_in_transaction=idle_tx,
        waiting_connections=waiting,
        max_connections=max_connections,
        usage_percent=round(usage, 2),
    )


# ---------------------------------------------------------------------------
# 3.3 postgres_slow_queries
# ---------------------------------------------------------------------------


def postgres_slow_queries(
    *,
    dsn: str,
    threshold_ms: int = 1000,
    limit: int = 50,
    timeout_sec: int = 5,
) -> list[SlowQuery]:
    """查 mean_time > threshold_ms 的慢查询 top N.

    Args:
        dsn: PostgreSQL connection string
        threshold_ms: 慢查询阈值 (毫秒)
        limit: 返回最多 N 条
        timeout_sec: 连接超时

    Returns:
        SlowQuery 列表，按 mean_time_ms 降序

    Raises:
        OprimConnectionError
        OprimError: 如果 pg_stat_statements 未启用
    """
    conn = _connect(dsn, timeout_sec)
    try:
        with conn.cursor() as cur:
            # Verify pg_stat_statements is available
            cur.execute("SELECT 1 FROM pg_extension WHERE extname = 'pg_stat_statements';")
            if cur.fetchone() is None:
                raise OprimError(
                    "pg_stat_statements extension is not installed. "
                    "Enable it with: CREATE EXTENSION pg_stat_statements;"
                )

            cur.execute(
                """
                SELECT queryid, LEFT(query, 500), calls,
                       total_exec_time, mean_exec_time, max_exec_time, rows
                FROM pg_stat_statements
                WHERE mean_exec_time > %s
                ORDER BY mean_exec_time DESC
                LIMIT %s;
                """,
                (threshold_ms, limit),
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    return [
        SlowQuery(
            query_id=int(row[0]),
            query_text=row[1] or "",
            calls=int(row[2]),
            total_time_ms=float(row[3]),
            mean_time_ms=float(row[4]),
            max_time_ms=float(row[5]),
            rows=int(row[6]),
        )
        for row in rows
    ]


# ---------------------------------------------------------------------------
# 3.4 postgres_locks_status
# ---------------------------------------------------------------------------


def postgres_locks_status(
    *,
    dsn: str,
    include_granted: bool = False,
    timeout_sec: int = 5,
) -> list[LockInfo]:
    """查 PostgreSQL 锁状态 (默认只返等待中的锁).

    Args:
        dsn: PostgreSQL connection string
        include_granted: 是否包含已授予的锁
        timeout_sec: 连接超时

    Returns:
        LockInfo 列表

    Raises:
        OprimConnectionError
    """
    conn = _connect(dsn, timeout_sec)
    try:
        with conn.cursor() as cur:
            granted_filter = "" if include_granted else "AND l.granted = false"
            cur.execute(
                f"""
                SELECT
                    l.locktype,
                    c.relname AS relation_name,
                    l.mode,
                    l.granted,
                    a.pid,
                    a.query,
                    a.wait_event_type,
                    EXTRACT(EPOCH FROM (NOW() - a.state_change)) AS wait_duration_sec
                FROM pg_locks l
                LEFT JOIN pg_stat_activity a ON a.pid = l.pid
                LEFT JOIN pg_class c ON c.oid = l.relation
                WHERE a.pid IS NOT NULL
                {granted_filter}
                ORDER BY wait_duration_sec DESC NULLS LAST;
                """
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    return [
        LockInfo(
            locktype=row[0] or "",
            relation_name=row[1],
            mode=row[2] or "",
            granted=bool(row[3]),
            pid=int(row[4]),
            query=row[5],
            wait_event_type=row[6],
            wait_duration_sec=float(row[7]) if row[7] is not None else None,
        )
        for row in rows
    ]


# ---------------------------------------------------------------------------
# 3.5 postgres_table_size
# ---------------------------------------------------------------------------


def postgres_table_size(
    *,
    dsn: str,
    schema: str = "public",
    top_n: int = 50,
    timeout_sec: int = 10,
) -> list[TableSize]:
    """查 schema 内表大小 top N (含索引和 toast).

    Args:
        dsn: PostgreSQL connection string
        schema: 目标 schema
        top_n: 返回最大的 N 张表
        timeout_sec: 连接超时

    Returns:
        TableSize 列表，按 total_bytes 降序

    Raises:
        OprimConnectionError
    """
    conn = _connect(dsn, timeout_sec)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    schemaname AS schema,
                    tablename AS table_name,
                    pg_total_relation_size(schemaname || '.' || tablename) AS total_bytes,
                    pg_relation_size(schemaname || '.' || tablename) AS table_bytes,
                    pg_indexes_size(schemaname || '.' || tablename) AS indexes_bytes,
                    COALESCE(
                        pg_total_relation_size(schemaname || '.' || tablename)
                        - pg_relation_size(schemaname || '.' || tablename)
                        - pg_indexes_size(schemaname || '.' || tablename),
                        0
                    ) AS toast_bytes,
                    (SELECT reltuples::bigint FROM pg_class c
                     JOIN pg_namespace n ON n.oid = c.relnamespace
                     WHERE n.nspname = t.schemaname
                       AND c.relname = t.tablename) AS row_count_estimate
                FROM pg_tables t
                WHERE schemaname = %s
                ORDER BY total_bytes DESC
                LIMIT %s;
                """,
                (schema, top_n),
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    return [
        TableSize(
            schema_name=row[0],
            table_name=row[1],
            total_bytes=int(row[2] or 0),
            table_bytes=int(row[3] or 0),
            indexes_bytes=int(row[4] or 0),
            toast_bytes=int(row[5] or 0),
            row_count_estimate=int(row[6] or 0),
        )
        for row in rows
    ]


# ---------------------------------------------------------------------------
# 3.6 postgres_replication_lag
# ---------------------------------------------------------------------------


def postgres_replication_lag(
    *,
    dsn: str,
    timeout_sec: int = 5,
) -> ReplicationLag:
    """查主从复制延迟 (从 primary 角度).

    Args:
        dsn: PostgreSQL connection string (primary)
        timeout_sec: 连接超时

    Returns:
        ReplicationLag — max_lag_seconds=None 表示无 replica 或在 replica 上

    Raises:
        OprimConnectionError
    """
    conn = _connect(dsn, timeout_sec)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_is_in_recovery();")
            row = cur.fetchone()
            is_replica = bool(row[0]) if row else False
            is_primary = not is_replica

            replicas: list[dict[str, Any]] = []
            if is_primary:
                cur.execute(
                    """
                    SELECT
                        client_addr::text,
                        state,
                        sync_state,
                        COALESCE(
                            EXTRACT(EPOCH FROM (NOW() - write_lag)), 0
                        ) AS lag_seconds,
                        COALESCE(
                            pg_wal_lsn_diff(pg_current_wal_lsn(), sent_lsn), 0
                        ) AS lag_bytes
                    FROM pg_stat_replication;
                    """
                )
                for r in cur.fetchall():
                    replicas.append(
                        {
                            "client_addr": r[0],
                            "state": r[1],
                            "sync_state": r[2],
                            "lag_seconds": float(r[3]),
                            "lag_bytes": int(r[4]),
                        }
                    )
    finally:
        conn.close()

    max_lag = max((r["lag_seconds"] for r in replicas), default=None) if replicas else None

    return ReplicationLag(
        is_primary=is_primary,
        replicas=replicas,
        max_lag_seconds=max_lag,
    )


# ---------------------------------------------------------------------------
# Aegis IMPL SPEC v1.0 — short-name aliases (B2)
# ---------------------------------------------------------------------------

postgres_long_running_queries = postgres_slow_queries
postgres_locks = postgres_locks_status
