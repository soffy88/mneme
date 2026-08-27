"""Read-only migration preflight; never upgrades or downgrades a database."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from services.migration_preflight import migration_files_have_downgrades

EXPECTED_HEAD = "5e7f8a9b0c12"


def discovered_heads(root: Path) -> list[str]:
    result = subprocess.run(["uv", "run", "alembic", "heads"], cwd=root, capture_output=True, text=True, check=True)
    return [line.split()[0] for line in result.stdout.splitlines() if "(head)" in line]


def read_current_revision(database_url: str) -> str | None:
    """Read one revision in a caller-supplied environment; never writes."""

    sync_url = database_url.replace("+asyncpg", "")
    engine = create_engine(sync_url)
    try:
        with engine.connect() as connection:
            return connection.execute(text("SELECT version_num FROM alembic_version LIMIT 1")).scalar_one_or_none()
    finally:
        engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", help="explicit read-only URL; omitted means no database is contacted")
    parser.add_argument("--environment", default=os.environ.get("MNEME_ENV", "dev"))
    args = parser.parse_args()
    root = ROOT
    heads = discovered_heads(root)
    downgrades = migration_files_have_downgrades(root / "alembic" / "versions")
    print(f"EXPECTED_HEAD {EXPECTED_HEAD}")
    print(f"DISCOVERED_HEADS {','.join(heads)}")
    print(f"DOWNGRADE_FUNCTIONS {'PASS' if downgrades else 'FAIL'}")
    if heads != [EXPECTED_HEAD]:
        print("PRODUCTION DB PREFLIGHT FAILED: migration head is not unique or expected")
        return 1
    if not downgrades:
        print("PRODUCTION DB PREFLIGHT FAILED: a migration is missing downgrade")
        return 1
    if not args.database_url:
        print("PRODUCTION DB PREFLIGHT BLOCKED_OWNER: current revision not read; provide an explicitly approved read-only URL")
        print("No migration was executed and no production data was touched.")
        return 0
    if args.environment.lower() in {"prod", "production"} and os.environ.get("MNEME_ALLOW_READONLY_PRODUCTION_PREFLIGHT") != "1":
        print("PRODUCTION DB PREFLIGHT BLOCKED_OWNER: production read requires explicit owner approval")
        return 0
    try:
        current = read_current_revision(args.database_url)
    except Exception as exc:  # noqa: BLE001 - preflight reports infra state, never credentials
        print(f"CURRENT_REVISION READ_FAILED:{type(exc).__name__}")
        print("PRODUCTION DB PREFLIGHT BLOCKED_INFRA: database could not be read")
        return 0
    print(f"CURRENT_REVISION {current or 'UNKNOWN'}")
    if current != EXPECTED_HEAD:
        print("PRODUCTION DB PREFLIGHT FAILED: current revision differs from expected head")
        return 1
    print("PRODUCTION DB PREFLIGHT PASS (read-only)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
