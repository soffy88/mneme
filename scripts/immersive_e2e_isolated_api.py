#!/usr/bin/env python3
"""Start an isolated Immersive Learning API for merge-gate live E2E.

Uses ``mneme_test`` only. Patches MinIO media I/O to a local temp directory so
this never writes production object storage. Binds 127.0.0.1 (or container
0.0.0.0 behind a loopback-published port) — never the production :8000 compose
API.

Ephemeral ports: set IMMERSIVE_E2E_PORT=0 and IMMERSIVE_E2E_PORT_FILE=/path;
the bound port is written after listen.
"""

from __future__ import annotations

import os
import socket
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _bootstrap_sys_path() -> None:
    """Vendor-first path; drop cwd so /app/oprim cannot shadow vendor/oprim."""
    # Match production compose: `cd /tmp` before uvicorn so '' ≠ /app.
    try:
        os.chdir("/tmp")
    except OSError:
        os.chdir(tempfile.gettempdir())
    while "" in sys.path:
        sys.path.remove("")
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


_bootstrap_sys_path()

# Fail-closed: require explicit test DB URL; never default to production mneme.
TEST_DB = os.environ.get("IMMERSIVE_E2E_DATABASE_URL") or os.environ.get("DATABASE_URL")
if not TEST_DB or "/mneme_test" not in TEST_DB:
    sys.stderr.write(
        "REFUSING: set IMMERSIVE_E2E_DATABASE_URL (or DATABASE_URL) to …/mneme_test\n"
    )
    sys.exit(2)

# Safety: never aim at public production hostnames.
_lower = TEST_DB.lower()
for banned in ("sxueji.com", "api.sxueji.com"):
    if banned in _lower:
        sys.stderr.write(f"REFUSING: DATABASE_URL mentions {banned}\n")
        sys.exit(2)

os.environ["DATABASE_URL"] = TEST_DB
os.environ["IMMERSIVE_LEARNING_ENABLED"] = "1"
os.environ["MNEME_ENV"] = os.environ.get("MNEME_ENV", "test")
os.environ.setdefault("REGISTRATION_OPEN", "1")
os.environ.setdefault("SMS_PROVIDER", "mock")
# Isolated E2E must not block on full-repo AST sandbox scan (can hang on large trees).
os.environ["MNEME_SKIP_SANDBOX_SELFCHECK"] = "1"
# Keep bytecode off the congested /data volume (host D-state root cause).
os.environ.setdefault("PYTHONPYCACHEPREFIX", "/tmp/mneme-immersive-e2e-pycache")
Path(os.environ["PYTHONPYCACHEPREFIX"]).mkdir(parents=True, exist_ok=True)

BLOB_ROOT = Path(
    os.environ.get("IMMERSIVE_E2E_BLOB_ROOT", tempfile.mkdtemp(prefix="immersive-e2e-"))
)
BLOB_ROOT.mkdir(parents=True, exist_ok=True)


def _pick_port(host: str, requested: int) -> int:
    if requested > 0:
        return requested
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((host if host not in {"0.0.0.0", "::"} else "127.0.0.1", 0))
        return int(sock.getsockname()[1])


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


def _assert_import_vendor_oprim() -> None:
    import oprim

    oprim_file = Path(getattr(oprim, "__file__", "") or "")
    if "vendor" not in str(oprim_file).replace("\\", "/"):
        sys.stderr.write(
            f"REFUSING: oprim resolved to {oprim_file} (need vendor/oprim)\n"
        )
        sys.exit(3)
    try:
        from oprim import file_read  # noqa: F401
    except ImportError as exc:
        sys.stderr.write(f"REFUSING: vendor oprim missing file_read: {exc}\n")
        sys.exit(3)


def main() -> None:
    host = os.environ.get("IMMERSIVE_E2E_HOST", "127.0.0.1")
    requested = int(os.environ.get("IMMERSIVE_E2E_PORT", "0"))
    # Refuse binding the live production published port on the host loopback.
    if host in {"127.0.0.1", "localhost"} and requested == 8000:
        sys.stderr.write("REFUSING: will not bind host :8000 (production API)\n")
        sys.exit(2)

    port = _pick_port(host, requested)
    port_file = os.environ.get("IMMERSIVE_E2E_PORT_FILE", "").strip()
    if port_file:
        Path(port_file).write_text(str(port), encoding="utf-8")

    _assert_import_vendor_oprim()
    _patch_storage()
    # Import the app object in THIS process so sys.path + storage patches apply.
    from services.main import app
    import uvicorn

    print(
        f"IMMERSIVE E2E API on http://{host}:{port} db=mneme_test blobs={BLOB_ROOT}",
        flush=True,
    )
    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    main()
