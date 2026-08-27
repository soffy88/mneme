"""Small liveness/readiness contracts shared by HTTP and launch checks."""

from __future__ import annotations

from typing import Any


def health_payload(*, version: str = "0.1.0") -> dict[str, Any]:
    """Liveness only: process is alive; dependencies are deliberately omitted."""

    return {"status": "ok", "service": "mneme-api", "version": version}


def readiness_payload(
    *,
    database: bool,
    migrations: bool,
    storage: bool = True,
    noncritical: dict[str, bool] | None = None,
) -> tuple[dict[str, Any], int]:
    """Build a dependency-aware readiness response.

    Only database, migration compatibility, and required storage are critical.
    LLM/Redis/worker status is visible but does not make deterministic learning
    data unavailable by itself.
    """

    dependencies = {"database": database, "migrations": migrations, "storage": storage}
    dependencies.update(noncritical or {})
    ready = database and migrations and storage
    return {"status": "ready" if ready else "not_ready", "dependencies": dependencies}, 200 if ready else 503


__all__ = ["health_payload", "readiness_payload"]
