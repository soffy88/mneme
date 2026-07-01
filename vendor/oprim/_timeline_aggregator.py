"""oprim.timeline_aggregator — Aggregate timestamped items into time buckets.

3O layer: oprim (single atomic aggregation, pure logic, no LLM).
Groups items by day/week/month bucket from ISO timestamp field.
"""

from __future__ import annotations

from datetime import datetime, timezone


def timeline_aggregator(
    *,
    items: list[dict],
    timestamp_field: str = "pub_date",
    granularity: str = "day",  # "day" | "week" | "month"
    sort_desc: bool = True,
) -> dict:
    """Group timestamped items into time buckets.

    Returns: {
        buckets: [{period: str, items: list, count: int}],
        total_items: int,
        earliest: str|None,
        latest: str|None,
        error: str|None,
    }
    """
    result: dict = {
        "buckets": [],
        "total_items": 0,
        "earliest": None,
        "latest": None,
        "error": None,
    }

    if not items:
        return result

    valid_granularities = {"day", "week", "month"}
    if granularity not in valid_granularities:
        result["error"] = (
            f"unknown granularity '{granularity}'; must be one of {sorted(valid_granularities)}"
        )
        return result

    try:
        buckets: dict[str, list[dict]] = {}
        parsed_dates: list[datetime] = []

        for item in items:
            ts_raw = item.get(timestamp_field)
            if ts_raw is None:
                continue

            try:
                dt = _parse_iso(ts_raw)
            except (ValueError, TypeError):
                continue

            parsed_dates.append(dt)
            period = _period_key(dt, granularity)

            if period not in buckets:
                buckets[period] = []
            buckets[period].append(item)

        if not buckets:
            return result

        sorted_periods = sorted(buckets.keys(), reverse=sort_desc)
        result["buckets"] = [
            {"period": p, "items": buckets[p], "count": len(buckets[p])} for p in sorted_periods
        ]
        result["total_items"] = sum(len(v) for v in buckets.values())

        if parsed_dates:
            result["earliest"] = min(parsed_dates).isoformat()
            result["latest"] = max(parsed_dates).isoformat()

    except Exception as exc:
        result["error"] = str(exc)

    return result


def _parse_iso(value: str) -> datetime:
    """Parse ISO 8601 timestamp, returning UTC-aware datetime."""
    # Python 3.7+ fromisoformat does not handle 'Z' suffix
    if isinstance(value, datetime):
        return value
    s = str(value).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _period_key(dt: datetime, granularity: str) -> str:
    """Return bucket key string for the given datetime and granularity."""
    if granularity == "day":
        return dt.strftime("%Y-%m-%d")
    elif granularity == "week":
        # ISO year-week, e.g. "2024-W03"
        iso = dt.isocalendar()
        return f"{iso[0]}-W{iso[1]:02d}"
    else:  # month
        return dt.strftime("%Y-%m")
