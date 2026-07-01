from datetime import datetime
from typing import Any, cast

from pydantic import BaseModel


class CorrelatedEvents(BaseModel):
    target_event_id: str
    causally_related: list[dict[str, Any]]       # 通过 parent_id / root_cause_id 链接
    time_window_correlated: list[dict[str, Any]] # 时间窗内, 但无显式因果链
    confidence: float                  # 关联可信度


def event_trail_correlate(
    *,
    target_event_id: str,
    all_events: list[dict[str, Any]],
    time_window_sec: int = 300,
    causal_keys: tuple[str, ...] = ("parent_id", "root_cause_id"),
) -> CorrelatedEvents:
    """按因果链 + 时间窗关联事件.

    纯计算 oskill, 不调外部.
    """
    event_map = {str(e.get("id") or e.get("event_id")): e for e in all_events if e.get("id") or e.get("event_id")}

    target_event = event_map.get(target_event_id)
    if not target_event:
        raise ValueError(f"Target event {target_event_id} not found in all_events")

    causally_related: set[str] = set()

    # 1. Trace causal chain (Ancestors and Descendants)
    to_visit = [target_event_id]
    visited = set()
    while to_visit:
        current_id = to_visit.pop(0)
        if current_id in visited:
            continue
        visited.add(current_id)

        if current_id != target_event_id:
            causally_related.add(current_id)

        # Find descendants (events that point to current as parent/root_cause)
        for eid, e in event_map.items():
            for key in causal_keys:
                if str(e.get(key)) == current_id:
                    to_visit.append(eid)

    # BFS for ancestors
    to_visit = [target_event_id]
    while to_visit:
        current_id = to_visit.pop(0)
        current_event = event_map.get(current_id)
        if not current_event:
            continue

        for key in causal_keys:
            parent_id = cast(str | None, current_event.get(key))
            if parent_id:
                parent_id_str = str(parent_id)
                if parent_id_str in event_map and parent_id_str not in visited:
                    causally_related.add(parent_id_str)
                    visited.add(parent_id_str)
                    to_visit.append(parent_id_str)

    # 2. Time window correlation
    time_window_correlated: set[str] = set()
    target_ts_str = cast(str | None, target_event.get("timestamp") or target_event.get("created_at"))
    if target_ts_str:
        try:
            target_ts = datetime.fromisoformat(target_ts_str.replace("Z", "+00:00"))
            for eid, e in event_map.items():
                if eid == target_event_id or eid in causally_related:
                    continue

                ts_str = cast(str | None, e.get("timestamp") or e.get("created_at"))
                if ts_str:
                    try:
                        ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                        if abs((ts - target_ts).total_seconds()) <= time_window_sec:
                            time_window_correlated.add(eid)
                    except (ValueError, TypeError):
                        pass
        except (ValueError, TypeError):
            pass

    causal_list = [event_map[eid] for eid in causally_related if eid in event_map]
    time_list = [event_map[eid] for eid in time_window_correlated if eid in event_map]

    confidence = 1.0 if causal_list else (0.5 if time_list else 0.0)

    return CorrelatedEvents(
        target_event_id=target_event_id,
        causally_related=causal_list,
        time_window_correlated=time_list,
        confidence=confidence
    )
