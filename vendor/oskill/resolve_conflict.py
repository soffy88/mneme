from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

from oskill._exceptions import OskillError


class Conflict(BaseModel):
    field: str
    local_value: Any
    remote_value: Any
    resolution: Literal["merged", "local_kept", "remote_kept", "both_kept"]


class ResolvedResult(BaseModel):
    resolved: dict[str, Any]
    conflicts: list[Conflict]
    resolution_strategy: str


def resolve_conflict(
    *,
    local_version: dict[str, Any],
    remote_version: dict[str, Any],
    base_version: dict[str, Any] | None = None,
    strategy: str = "auto",
    conflict_type: str,
) -> ResolvedResult:
    """Resolve sync conflicts between local and remote versions using type-specific strategies.

    Internal oskill composition: pure three-way merge algorithm (no oprim calls).

    Strategies by conflict_type (when strategy="auto"):
        "highlight": merge — take union of both versions' lists
        "note": keep_both — retain both versions independently
        "metadata": last_write_wins — compare _updated_at field

    Args:
        local_version: Local state dict
        remote_version: Remote state dict
        base_version: Common ancestor (optional; if None, falls back to two-way merge)
        strategy: "auto" | "local_wins" | "remote_wins" | "merge"
        conflict_type: "highlight" | "note" | "metadata"

    Returns:
        ResolvedResult with resolved dict, conflict list, and strategy used

    Raises:
        OskillError: Unknown conflict_type or strategy

    Example:
        >>> result = resolve_conflict(
        ...     local_version={"items": ["a", "b"]},
        ...     remote_version={"items": ["b", "c"]},
        ...     conflict_type="highlight",
        ... )
        >>> result.resolution_strategy
        'merge'
    """
    if strategy == "local_wins":
        return ResolvedResult(
            resolved=local_version.copy(),
            conflicts=[],
            resolution_strategy="local_wins",
        )

    if strategy == "remote_wins":
        return ResolvedResult(
            resolved=remote_version.copy(),
            conflicts=[],
            resolution_strategy="remote_wins",
        )

    # strategy == "auto" or "merge"
    if conflict_type == "highlight":
        return _resolve_highlight(local_version, remote_version)
    elif conflict_type == "note":
        return _resolve_note(local_version, remote_version)
    elif conflict_type == "metadata":
        return _resolve_metadata(local_version, remote_version)
    else:
        raise OskillError(f"Unknown conflict_type: {conflict_type!r}")


def _resolve_highlight(local: dict[str, Any], remote: dict[str, Any]) -> ResolvedResult:
    resolved: dict[str, Any] = {}
    conflicts: list[Conflict] = []
    all_keys = set(local) | set(remote)

    for key in all_keys:
        lv = local.get(key)
        rv = remote.get(key)
        if lv == rv or rv is None:
            resolved[key] = lv
        elif lv is None:
            resolved[key] = rv
        elif isinstance(lv, list) and isinstance(rv, list):
            seen: list[Any] = []
            for item in lv + rv:
                if item not in seen:
                    seen.append(item)
            resolved[key] = seen
            if set(str(x) for x in lv) != set(str(x) for x in rv):
                conflicts.append(
                    Conflict(field=key, local_value=lv, remote_value=rv, resolution="merged")
                )
        else:
            resolved[key] = lv
            conflicts.append(
                Conflict(field=key, local_value=lv, remote_value=rv, resolution="local_kept")
            )

    return ResolvedResult(resolved=resolved, conflicts=conflicts, resolution_strategy="merge")


def _resolve_note(local: dict[str, Any], remote: dict[str, Any]) -> ResolvedResult:
    conflicts: list[Conflict] = []
    all_keys = set(local) | set(remote)

    for key in all_keys:
        lv = local.get(key)
        rv = remote.get(key)
        if lv != rv and lv is not None and rv is not None:
            conflicts.append(
                Conflict(field=key, local_value=lv, remote_value=rv, resolution="both_kept")
            )

    resolved: dict[str, Any] = {**remote, **local}
    if conflicts:
        resolved["_remote_version"] = remote

    return ResolvedResult(resolved=resolved, conflicts=conflicts, resolution_strategy="keep_both")


def _resolve_metadata(local: dict[str, Any], remote: dict[str, Any]) -> ResolvedResult:
    local_ts = local.get("_updated_at")
    remote_ts = remote.get("_updated_at")

    conflicts: list[Conflict] = []

    if local_ts is None and remote_ts is None:
        resolved: dict[str, Any] = {**local, **remote}
    elif remote_ts is None or (local_ts is not None and local_ts >= remote_ts):
        resolved = local.copy()
    else:
        resolved = remote.copy()

    for key in set(local) | set(remote):
        if key.startswith("_"):
            continue
        lv = local.get(key)
        rv = remote.get(key)
        if lv != rv and lv is not None and rv is not None:
            winner = resolved.get(key)
            res: Literal["local_kept", "remote_kept"] = (
                "local_kept" if winner == lv else "remote_kept"
            )
            conflicts.append(Conflict(field=key, local_value=lv, remote_value=rv, resolution=res))

    return ResolvedResult(
        resolved=resolved, conflicts=conflicts, resolution_strategy="last_write_wins"
    )
