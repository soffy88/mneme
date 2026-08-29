#!/usr/bin/env python3
"""Start an isolated Immersive Learning API for merge-gate live E2E.

Uses ``mneme_test`` only. Patches MinIO media I/O to a local temp directory so
this never writes production object storage. Listens on 127.0.0.1:18000 by
default — never bind to the production :8000 compose API.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Same vendor-first order as tests/conftest.py (local oprim/ must not shadow vendor).
for entry in (
    ROOT,
    ROOT / "packages" / "event-schema",
    ROOT / "packages" / "mneme-agent",
    ROOT / "packages" / "mneme-core",
    ROOT / "vendor",
):
    value = str(entry)
    if value in sys.path:
        sys.path.remove(value)
    sys.path.insert(0, value)

# Fail-closed: require explicit test DB URL; never default to production mneme.
TEST_DB = os.environ.get("IMMERSIVE_E2E_DATABASE_URL") or os.environ.get("DATABASE_URL")
if not TEST_DB or "/mneme_test" not in TEST_DB:
    sys.stderr.write(
        "REFUSING: set IMMERSIVE_E2E_DATABASE_URL (or DATABASE_URL) to …/mneme_test\n"
    )
    sys.exit(2)

os.environ["DATABASE_URL"] = TEST_DB
os.environ["IMMERSIVE_LEARNING_ENABLED"] = "1"
os.environ.setdefault("REGISTRATION_OPEN", "1")
# Isolated E2E must not block on full-repo AST sandbox scan (can hang on large trees).
os.environ["MNEME_SKIP_SANDBOX_SELFCHECK"] = "1"

BLOB_ROOT = Path(os.environ.get("IMMERSIVE_E2E_BLOB_ROOT", tempfile.mkdtemp(prefix="immersive-e2e-")))
BLOB_ROOT.mkdir(parents=True, exist_ok=True)


def _patch_storage() -> None:
    import services.storage as storage

    def _path(object_path: str) -> Path:
        safe = object_path.lstrip("/").replace("..", "_")
        target = BLOB_ROOT / safe
        target.parent.mkdir(parents=True, exist_ok=True)
        return target

    def upload_media_file(object_path: str, data: bytes, content_type: str) -> None:
        _path(object_path).write_bytes(data)

    def download_media_file(object_path: str) -> bytes:
        p = _path(object_path)
        if not p.exists():
            raise FileNotFoundError(object_path)
        return p.read_bytes()

    def delete_media_file(object_path: str) -> None:
        p = _path(object_path)
        p.unlink(missing_ok=True)

    def ensure_media_bucket() -> None:
        return None

    def presign_media_get_url(object_path: str, expires_seconds: int = 3600) -> str:
        # Local file URL for e2e only — never persisted as storage_ref.
        return f"file://{_path(object_path)}"

    storage.upload_media_file = upload_media_file  # type: ignore[assignment]
    storage.download_media_file = download_media_file  # type: ignore[assignment]
    storage.delete_media_file = delete_media_file  # type: ignore[assignment]
    storage.ensure_media_bucket = ensure_media_bucket  # type: ignore[assignment]
    storage.presign_media_get_url = presign_media_get_url  # type: ignore[assignment]


def main() -> None:
    host = os.environ.get("IMMERSIVE_E2E_HOST", "127.0.0.1")
    port = int(os.environ.get("IMMERSIVE_E2E_PORT", "18000"))
    _patch_storage()
    # Import the app object in THIS process so sys.path + storage patches apply.
    # (String import "services.main:app" would re-resolve path and can hang/shadow.)
    from services.main import app
    import uvicorn

    print(
        f"IMMERSIVE E2E API on http://{host}:{port} db=mneme_test blobs={BLOB_ROOT}",
        flush=True,
    )
    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    main()
