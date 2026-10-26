#!/usr/bin/env python3
"""Fill vocab_media_availability from PUBLIC_MANIFEST.json (test DB only).

Reads the upstream manifest's items[].path set, stages it in a TEMP table,
then upserts one row per vocab_units id with the six existence bits
(img/thumb/uk/us/ex/ex2). Re-running recomputes the whole table
(idempotent). Refuses any database that is not mneme_test.

Expected counts (integration-3 dry run, manifest 37,725 items):
    total=7298, full_6=1011, missing_ex2=6287, other missing=0.
The script exits non-zero if the filled counts differ, so a manifest
version or staging problem cannot silently pass as data.

Usage (on ubuntu26):
    python3 fill_word_atlas_media_availability.py \\
        --manifest PUBLIC_MANIFEST.json \\
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

EXPECTED = {
    "total": 7298,
    "full_6": 1011,
    "missing_ex2": 6287,
    "missing_img": 0,
    "missing_thumb": 0,
    "missing_uk": 0,
    "missing_us": 0,
    "missing_ex": 0,
}


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
    ap.add_argument("--manifest", required=True,
                    help="Path to PUBLIC_MANIFEST.json")
    ap.add_argument("--dsn", default=None)
    ap.add_argument("--env-file", default=None)
    args = ap.parse_args()

    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    paths = [item["path"] for item in manifest["items"]]
    print(f"manifest items: {len(paths)} (header files: "
          f"{manifest.get('files')})")
    dsn = resolve_dsn(args.dsn, Path(args.env_file) if args.env_file else None)

    try:
        import psycopg2
        from psycopg2.extras import execute_values
    except ImportError:
        try:
            import psycopg as psycopg2  # type: ignore[no-redef]
            execute_values = None
        except ImportError as exc:
            raise SystemExit("Need psycopg2 or psycopg installed") from exc

    conn = psycopg2.connect(dsn)
    try:
        with conn.cursor() as cur:
            cur.execute("CREATE TEMP TABLE manifest_files (path TEXT PRIMARY KEY)")
            if execute_values is not None:
                execute_values(
                    cur, "INSERT INTO manifest_files (path) VALUES %s "
                    "ON CONFLICT DO NOTHING",
                    [(p,) for p in paths], page_size=1000)
            else:
                cur.executemany(
                    "INSERT INTO manifest_files (path) VALUES (%s) "
                    "ON CONFLICT DO NOTHING", [(p,) for p in paths])
            cur.execute("SELECT count(*) FROM manifest_files")
            print(f"staged manifest paths: {cur.fetchone()[0]}")
            cur.execute(
                "INSERT INTO vocab_media_availability"
                " (id, has_img, has_thumb, has_audio_uk, has_audio_us,"
                "  has_audio_ex, has_audio_ex2, manifest_checked_at)"
                " SELECT v.id,"
                "  EXISTS (SELECT 1 FROM manifest_files f"
                "   WHERE f.path = 'public/atlas/img/' || v.id || '.webp'),"
                "  EXISTS (SELECT 1 FROM manifest_files f"
                "   WHERE f.path = 'public/atlas/thumb/' || v.id || '.webp'),"
                "  EXISTS (SELECT 1 FROM manifest_files f"
                "   WHERE f.path = 'public/atlas/audio/uk/' || v.id || '.mp3'),"
                "  EXISTS (SELECT 1 FROM manifest_files f"
                "   WHERE f.path = 'public/atlas/audio/us/' || v.id || '.mp3'),"
                "  EXISTS (SELECT 1 FROM manifest_files f"
                "   WHERE f.path = 'public/atlas/audio/ex/' || v.id || '.mp3'),"
                "  EXISTS (SELECT 1 FROM manifest_files f"
                "   WHERE f.path = 'public/atlas/audio/ex2/' || v.id || '.mp3'),"
                "  now()"
                " FROM vocab_units v"
                " ON CONFLICT (id) DO UPDATE SET"
                "  has_img = EXCLUDED.has_img,"
                "  has_thumb = EXCLUDED.has_thumb,"
                "  has_audio_uk = EXCLUDED.has_audio_uk,"
                "  has_audio_us = EXCLUDED.has_audio_us,"
                "  has_audio_ex = EXCLUDED.has_audio_ex,"
                "  has_audio_ex2 = EXCLUDED.has_audio_ex2,"
                "  manifest_checked_at = EXCLUDED.manifest_checked_at")
            cur.execute(
                "SELECT count(*),"
                " count(*) FILTER (WHERE has_img AND has_thumb"
                "  AND has_audio_uk AND has_audio_us AND has_audio_ex"
                "  AND has_audio_ex2),"
                " count(*) FILTER (WHERE NOT has_audio_ex2),"
                " count(*) FILTER (WHERE NOT has_img),"
                " count(*) FILTER (WHERE NOT has_thumb),"
                " count(*) FILTER (WHERE NOT has_audio_uk),"
                " count(*) FILTER (WHERE NOT has_audio_us),"
                " count(*) FILTER (WHERE NOT has_audio_ex)"
                " FROM vocab_media_availability")
            row = cur.fetchone()
        counts = dict(zip(
            ["total", "full_6", "missing_ex2", "missing_img",
             "missing_thumb", "missing_uk", "missing_us", "missing_ex"],
            row))
        print(f"filled: {counts}")
        conn.commit()
    finally:
        conn.close()
    mismatches = {k: (counts[k], v) for k, v in EXPECTED.items()
                  if counts[k] != v}
    if mismatches:
        print(f"COUNT MISMATCH vs dry run: {mismatches}", file=sys.stderr)
        return 1
    print("counts match integration-3 dry run")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
