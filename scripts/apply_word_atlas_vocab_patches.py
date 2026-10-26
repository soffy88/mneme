#!/usr/bin/env python3
"""Apply Word Atlas vocab light-fix patches to mneme_test.vocab_units.

Idempotent, atomic, test-DB-only. Order of operations for the whole line:
    import -> apply this patch file -> validate.
Re-running the import overwrites the patched rows (ON CONFLICT DO UPDATE
from upstream JSON), so this script must be re-run after any import.

Per patch, exactly one of these outcomes is reported:
    APPLIED          current value equalled `old`, UPDATE written, re-read equals `new`
    SKIPPED          current value already equals `new` (patch already applied)
    APPLIED-RETAINED `retain` action: current value equals old == new, no write
                     needed (used for short-weight, where the sample report
                     requires keeping the note verbatim and excluding the word
                     from the daily queue in the queue layer, not a DB edit)
    CONFLICT         current value equals neither `old` nor `new`: NO write for
                     that row, whole transaction rolled back, exit code 1
    MISSING          no row with that id: same rollback + exit code 1

SAFETY: refuses any database that is not mneme_test. Only the fields listed
in ALLOWED_FIELDS may be patched. Credentials are never printed.

Usage (on ubuntu26):
    python3 apply_word_atlas_vocab_patches.py \
        --patches word-atlas-vocab-patches.json \
        --env-file /data/soffy/projects/mneme/.env
    # DSN resolution, same order as import_word_atlas_vocab.py:
    #   --dsn > $TEST_DATABASE_URL > $DATABASE_URL >
    #   postgresql://postgres:<POSTGRES_PASSWORD>@localhost:5433/mneme_test
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

ALLOWED_FIELDS = {"syn", "family", "note"}
TABLE = "vocab_units"


def _dbname_of(dsn: str) -> str:
    return urlparse(dsn).path.strip("/").split("?", 1)[0]


def _password_from_dotenv(*env_files: Path) -> str:
    for env_file in env_files:
        try:
            for line in env_file.read_text(encoding="utf-8").splitlines():
                if line.startswith("POSTGRES_PASSWORD="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
        except OSError:
            continue
    return ""


def resolve_dsn(explicit: str | None, env_file: Path | None) -> str:
    dsn = (explicit or os.environ.get("TEST_DATABASE_URL")
           or os.environ.get("DATABASE_URL") or "").strip()
    if not dsn:
        candidates = [env_file] if env_file is not None else []
        pw = os.environ.get("POSTGRES_PASSWORD", "").strip() \
            or _password_from_dotenv(*candidates)
        if not pw:
            raise SystemExit(
                "No DSN: pass --dsn, set TEST_DATABASE_URL/DATABASE_URL, "
                "or provide POSTGRES_PASSWORD / --env-file")
        dsn = f"postgresql://postgres:{pw}@localhost:5433/mneme_test"
    if _dbname_of(dsn) != "mneme_test":
        raise SystemExit(
            f"REFUSED: this script only writes mneme_test, got dbname "
            f"'{_dbname_of(dsn)}'. Production database mneme is off limits.")
    return dsn


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--patches", required=True,
                    help="Path to word-atlas-vocab-patches.json")
    ap.add_argument("--dsn", default=None)
    ap.add_argument("--env-file", default=None,
                    help="Optional .env file to read POSTGRES_PASSWORD from")
    args = ap.parse_args()

    data = json.loads(Path(args.patches).read_text(encoding="utf-8"))
    patches = data["patches"]
    dsn = resolve_dsn(args.dsn, Path(args.env_file) if args.env_file else None)

    try:
        import psycopg2
    except ImportError:
        try:
            import psycopg as psycopg2  # type: ignore[no-redef]
        except ImportError as exc:
            raise SystemExit("Need psycopg2 or psycopg installed") from exc

    records: list[dict] = []
    failed = False
    conn = psycopg2.connect(dsn)
    try:
        with conn.cursor() as cur:
            for p in patches:
                pid, field = p["id"], p["field"]
                if field not in ALLOWED_FIELDS:
                    records.append({"id": pid, "field": field,
                                    "status": "CONFLICT",
                                    "detail": f"field {field!r} not in allowlist"})
                    failed = True
                    continue
                cur.execute(
                    f"SELECT {field} FROM {TABLE} WHERE id = %s", (pid,))
                row = cur.fetchone()
                if row is None:
                    records.append({"id": pid, "field": field,
                                    "status": "MISSING",
                                    "detail": "no such row in vocab_units"})
                    failed = True
                    continue
                current = row[0]
                old, new = p["old"], p["new"]
                if p.get("action") == "retain":
                    if current == old == new:
                        records.append({"id": pid, "field": field,
                                        "status": "APPLIED-RETAINED",
                                        "detail": "value kept verbatim; no write"})
                    else:
                        records.append({"id": pid, "field": field,
                                        "status": "CONFLICT",
                                        "detail": "current value differs from patch old/new"})
                        failed = True
                    continue
                if current == new:
                    records.append({"id": pid, "field": field,
                                    "status": "SKIPPED",
                                    "detail": "already at new value"})
                elif current == old:
                    cur.execute(
                        f"UPDATE {TABLE} SET {field} = %s WHERE id = %s",
                        (new, pid))
                    cur.execute(
                        f"SELECT {field} FROM {TABLE} WHERE id = %s", (pid,))
                    if cur.fetchone()[0] == new:
                        records.append({"id": pid, "field": field,
                                        "status": "APPLIED",
                                        "detail": "old -> new verified by re-read"})
                    else:
                        records.append({"id": pid, "field": field,
                                        "status": "CONFLICT",
                                        "detail": "re-read after UPDATE did not match new"})
                        failed = True
                else:
                    records.append({"id": pid, "field": field,
                                    "status": "CONFLICT",
                                    "detail": "current value equals neither old nor new"})
                    failed = True
        if failed:
            conn.rollback()
            print("ROLLBACK: no patch was committed (a patch was "
                  "CONFLICT/MISSING; see records below)")
        else:
            conn.commit()
    finally:
        conn.close()

    for r in records:
        print(f"{r['status']:16} {r['id']:14} {r['field']:7} {r['detail']}")
    summary = {s: sum(1 for r in records if r["status"] == s)
               for s in ("APPLIED", "SKIPPED", "APPLIED-RETAINED",
                         "CONFLICT", "MISSING")}
    print(f"patches total={len(records)} applied={summary['APPLIED']} "
          f"skipped={summary['SKIPPED']} "
          f"retained={summary['APPLIED-RETAINED']} "
          f"conflict={summary['CONFLICT']} missing={summary['MISSING']} "
          f"committed={str(not failed).lower()}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
