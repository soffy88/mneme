"""IO write oprims — single DB/Redis write primitives.

Each function wraps exactly one write operation with injected executor.
"""

from __future__ import annotations

import json
from typing import Any


class WriteError(Exception):
    """Raised when an IO write oprim fails."""


async def write_rows(
    *,
    db: Any,
    rows: list[tuple],
    table: str = "cross_market_correlation",
) -> int:
    """Batch upsert rows to a correlation table.

    Args:
        db: Database executor implementing DbExecutor protocol.
        rows: List of row tuples to upsert.
        table: Target table name.

    Returns:
        Number of rows written.

    Raises:
        WriteError: On DB failure.

    Example:
        >>> await write_rows(db=d, rows=[(now, "BTC", "ETH", 30, None, 0.85, 28, "ok")])
        1
    """
    try:
        count = 0
        for row in rows:
            await db.execute(
                f"INSERT INTO {table} VALUES ({','.join(':p' + str(i) for i in range(len(row)))})"
                " ON CONFLICT DO UPDATE SET correlation = EXCLUDED.correlation",
                {f"p{i}": v for i, v in enumerate(row)},
            )
            count += 1
        return count
    except Exception as exc:
        raise WriteError(f"write_rows failed: {exc}") from exc


async def store_news(*, db: Any, items: list[dict]) -> int:
    """Insert news items (skip duplicates).

    Args:
        db: Database executor.
        items: List of {title, url, source, published_at, summary} dicts.

    Returns:
        Number of newly inserted rows.

    Raises:
        WriteError: On DB failure.

    Example:
        >>> await store_news(db=d, items=[{"title": "...", "url": "..."}])
        1
    """
    try:
        count = 0
        for item in items:
            r = await db.execute(
                "INSERT INTO news (title, url, source, published_at, summary) "
                "VALUES (:title, :url, :source, :published_at, :summary) "
                "ON CONFLICT (url) DO NOTHING",
                item,
            )
            count += r
        return count
    except Exception as exc:
        raise WriteError(f"store_news failed: {exc}") from exc


async def upsert_events(*, db: Any, rows: list[dict]) -> int:
    """Upsert calendar events (earnings/economic).

    Args:
        db: Database executor.
        rows: List of event dicts with keys matching event_calendar schema.

    Returns:
        Number of rows upserted.

    Raises:
        WriteError: On DB failure.

    Example:
        >>> await upsert_events(db=d, rows=[{"event_date": "2024-01-01", ...}])
        1
    """
    try:
        count = 0
        for row in rows:
            await db.execute(
                "INSERT INTO event_calendar (event_date, event_type, title, impact) "
                "VALUES (:event_date, :event_type, :title, :impact) "
                "ON CONFLICT DO NOTHING",
                row,
            )
            count += 1
        return count
    except Exception as exc:
        raise WriteError(f"upsert_events failed: {exc}") from exc


async def upsert_canonical_metric(*, db: Any, **kwargs: Any) -> str:
    """Upsert a full canonical metric row.

    Args:
        db: Database executor.
        **kwargs: Metric fields (agent, strategy, market, window_days, as_of_date, etc.).

    Returns:
        Generated UUID of the upserted row.

    Raises:
        WriteError: On DB failure.

    Example:
        >>> await upsert_canonical_metric(db=d, agent="helios", strategy="fusion", ...)
        'uuid-...'
    """
    try:
        row = await db.fetch_one(
            "INSERT INTO canonical_metric "
            "(agent, strategy, market, window_days, as_of_date, "
            "cumulative_pnl, max_drawdown, sharpe_ratio, sortino_ratio, "
            "calmar_ratio, volatility_annualized, trade_frequency) "
            "VALUES (:agent, :strategy, :market, :window_days, :as_of_date, "
            ":cumulative_pnl, :max_drawdown, :sharpe_ratio, :sortino_ratio, "
            ":calmar_ratio, :volatility_annualized, :trade_frequency) "
            "ON CONFLICT (agent, strategy, market, window_days, as_of_date) "
            "DO UPDATE SET cumulative_pnl = EXCLUDED.cumulative_pnl "
            "RETURNING id",
            kwargs,
        )
        return str(row["id"]) if row else ""
    except Exception as exc:
        raise WriteError(f"upsert_canonical_metric failed: {exc}") from exc


async def upsert_equity_series(
    *,
    db: Any,
    agent: str,
    strategy: str,
    market: str,
    as_of_date: str,
    equity: float,
    daily_return: float | None = None,
) -> None:
    """Upsert a single equity series data point.

    Args:
        db: Database executor.
        agent: Agent identifier.
        strategy: Strategy name.
        market: Market identifier.
        as_of_date: Date (ISO).
        equity: Equity value.
        daily_return: Optional daily return.

    Raises:
        WriteError: On DB failure.

    Example:
        >>> await upsert_equity_series(
        ...     db=d, agent="h", strategy="f", market="crypto",
        ...     as_of_date="2024-01-01", equity=10000.0,
        ... )
    """
    try:
        await db.execute(
            "INSERT INTO equity_series (agent, strategy, market, as_of_date, equity, daily_return) "
            "VALUES (:agent, :strategy, :market, :as_of_date, :equity, :daily_return) "
            "ON CONFLICT (agent, strategy, market, as_of_date) "
            "DO UPDATE SET equity = EXCLUDED.equity, daily_return = EXCLUDED.daily_return",
            {
                "agent": agent,
                "strategy": strategy,
                "market": market,
                "as_of_date": as_of_date,
                "equity": equity,
                "daily_return": daily_return,
            },
        )
    except Exception as exc:
        raise WriteError(f"upsert_equity_series failed: {exc}") from exc


async def write_event(
    *,
    db: Any,
    preset: str,
    trigger_data: dict,
    summary: str,
) -> str:
    """Create alert + black swan event.

    Args:
        db: Database executor.
        preset: Event preset identifier.
        trigger_data: JSON-serializable trigger data.
        summary: Human-readable summary.

    Returns:
        Event UUID.

    Raises:
        WriteError: On DB failure.

    Example:
        >>> await write_event(db=d, preset="btc_crash", trigger_data={}, summary="BTC -10%")
        'uuid-...'
    """
    try:
        row = await db.fetch_one(
            "INSERT INTO black_swan_events (preset, trigger_data, summary) "
            "VALUES (:preset, :trigger_data, :summary) RETURNING id",
            {"preset": preset, "trigger_data": json.dumps(trigger_data), "summary": summary},
        )
        return str(row["id"]) if row else ""
    except Exception as exc:
        raise WriteError(f"write_event failed: {exc}") from exc


async def clear_event(*, db: Any, event_id: str, reason: str) -> None:
    """Mark a black swan event as cleared.

    Args:
        db: Database executor.
        event_id: Event UUID to clear.
        reason: Reason for clearing.

    Raises:
        WriteError: On DB failure.

    Example:
        >>> await clear_event(db=d, event_id="uuid-...", reason="recovered")
    """
    try:
        await db.execute(
            "UPDATE black_swan_events SET cleared_at = NOW(), clear_reason = :reason "
            "WHERE id = :id",
            {"id": event_id, "reason": reason},
        )
    except Exception as exc:
        raise WriteError(f"clear_event failed: {exc}") from exc


async def is_deduped(*, db: Any, preset: str, hours: int = 24) -> bool:
    """Check if a recent event exists within dedup window.

    Args:
        db: Database executor.
        preset: Event preset.
        hours: Dedup window in hours.

    Returns:
        True if a recent event exists.

    Raises:
        WriteError: On DB failure.

    Example:
        >>> await is_deduped(db=d, preset="btc_crash")
        False
    """
    try:
        row = await db.fetch_one(
            "SELECT 1 FROM black_swan_events "
            "WHERE preset = :preset "
            "AND created_at >= NOW() - INTERVAL ':hours hours'",
            {"preset": preset, "hours": hours},
        )
        return row is not None
    except Exception as exc:
        raise WriteError(f"is_deduped failed: {exc}") from exc


async def refresh_view(*, db: Any, view: str, concurrently: bool = True) -> dict:
    """Refresh a materialized view.

    Args:
        db: Database executor.
        view: View name.
        concurrently: Whether to refresh concurrently.

    Returns:
        Dict with {view, concurrently, status}.

    Raises:
        WriteError: On DB failure.

    Example:
        >>> await refresh_view(db=d, view="mv_daily_summary")
        {'view': 'mv_daily_summary', 'concurrently': True, 'status': 'ok'}
    """
    try:
        conc = "CONCURRENTLY" if concurrently else ""
        await db.execute(f"REFRESH MATERIALIZED VIEW {conc} {view}")
        return {"view": view, "concurrently": concurrently, "status": "ok"}
    except Exception as exc:
        raise WriteError(f"refresh_view failed: {exc}") from exc


async def send_alert(
    *,
    cache: Any,
    level: str,
    title: str,
    message: str,
) -> None:
    """Publish alert to Redis pubsub channel.

    Args:
        cache: Cache client with publish capability.
        level: Alert level (info/warn/critical).
        title: Alert title.
        message: Alert body.

    Raises:
        WriteError: On publish failure.

    Example:
        >>> await send_alert(cache=c, level="warn", title="Stale", message="...")
    """
    try:
        payload = json.dumps({"level": level, "title": title, "message": message})
        await cache.publish("alerts", payload)
    except Exception as exc:
        raise WriteError(f"send_alert failed: {exc}") from exc
