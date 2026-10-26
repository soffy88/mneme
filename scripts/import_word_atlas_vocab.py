#!/usr/bin/env python3
"""Idempotent import of Word Atlas vocabulary into mneme_test.vocab_units.

Source: designfuchen/word-atlas, data/word-atlas.json (local copy passed
with --json). License of the word list / illustrations / recordings is
CC BY 4.0; every row carries attribution
"Word Atlas contributors \u2014 CC BY 4.0".

SAFETY: this script refuses any database that is not mneme_test. It never
touches the production database mneme, never deploys, never pushes.
Re-running it with the same input leaves the row count unchanged
(INSERT ... ON CONFLICT (id) DO UPDATE).

Usage (on ubuntu26, from the mneme worktree):
    python3 scripts/import_word_atlas_vocab.py \
        --json /path/to/word-atlas.json
    # DSN resolution, in order: --dsn, $TEST_DATABASE_URL, $DATABASE_URL,
    # then postgresql://postgres:<POSTGRES_PASSWORD>@localhost:5433/mneme_test
    # where POSTGRES_PASSWORD comes from $POSTGRES_PASSWORD or <repo>/.env.
    # The password is never printed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

ATTRIBUTION = "Word Atlas contributors \u2014 CC BY 4.0"
SOURCE = "word-atlas"
CEFR_LEVELS = {"A1", "A2", "B1", "B2", "C1", "C2"}
BATCH = 500

DDL = """
CREATE TABLE IF NOT EXISTS vocab_units (
    id           TEXT PRIMARY KEY,
    word         TEXT NOT NULL,
    uk           TEXT NOT NULL DEFAULT '',
    us           TEXT NOT NULL DEFAULT '',
    senses       JSONB NOT NULL DEFAULT '[]'::jsonb,
    examples     JSONB NOT NULL DEFAULT '[]'::jsonb,
    collocations TEXT[] NOT NULL DEFAULT '{}',
    family       TEXT[] NOT NULL DEFAULT '{}',
    syn          TEXT[] NOT NULL DEFAULT '{}',
    ant          TEXT[] NOT NULL DEFAULT '{}',
    tip          TEXT NOT NULL DEFAULT '',
    cefr         TEXT NOT NULL,
    topic        TEXT NOT NULL,
    note         TEXT NOT NULL DEFAULT '',
    source       TEXT NOT NULL DEFAULT 'word-atlas',
    attribution  TEXT NOT NULL DEFAULT 'Word Atlas contributors \u2014 CC BY 4.0'
);
CREATE INDEX IF NOT EXISTS idx_vocab_units_cefr ON vocab_units (cefr);
CREATE INDEX IF NOT EXISTS idx_vocab_units_topic ON vocab_units (topic);
"""

UPSERT = """
INSERT INTO vocab_units
    (id, word, uk, us, senses, examples, collocations, family, syn, ant,
     tip, cefr, topic, note, source, attribution)
VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (id) DO UPDATE SET
    word = EXCLUDED.word, uk = EXCLUDED.uk, us = EXCLUDED.us,
    senses = EXCLUDED.senses, examples = EXCLUDED.examples,
    collocations = EXCLUDED.collocations, family = EXCLUDED.family,
    syn = EXCLUDED.syn, ant = EXCLUDED.ant, tip = EXCLUDED.tip,
    cefr = EXCLUDED.cefr, topic = EXCLUDED.topic, note = EXCLUDED.note,
    source = EXCLUDED.source, attribution = EXCLUDED.attribution
"""


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


def resolve_dsn(explicit: str | None, repo_root: Path,
                env_file: Path | None = None) -> str:
    dsn = (explicit or os.environ.get("TEST_DATABASE_URL")
           or os.environ.get("DATABASE_URL") or "").strip()
    if not dsn:
        candidates = [repo_root / ".env"]
        if env_file is not None:
            candidates.insert(0, env_file)
        pw = os.environ.get("POSTGRES_PASSWORD", "").strip() \
            or _password_from_dotenv(*candidates)
        if not pw:
            raise SystemExit(
                "No DSN: pass --dsn, set TEST_DATABASE_URL, or provide "
                "POSTGRES_PASSWORD / <repo>/.env")
        dsn = f"postgresql://postgres:{pw}@localhost:5433/mneme_test"
    if _dbname_of(dsn) != "mneme_test":
        raise SystemExit(
            f"REFUSED: this script only writes mneme_test, got dbname "
            f"'{_dbname_of(dsn)}'. Production database mneme is off limits.")
    return dsn


def load_rows(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise SystemExit(f"Expected a JSON list in {path}, got {type(data)}")
    seen: set[str] = set()
    rows = []
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            raise SystemExit(f"Entry {i} is not an object")
        vid = str(item.get("id") or "").strip()
        word = str(item.get("w") or "").strip()
        cefr = str(item.get("cefr") or "").strip()
        topic = str(item.get("topic") or "").strip()
        if not vid or not word or not cefr or not topic:
            raise SystemExit(f"Entry {i} missing id/w/cefr/topic: {item!r}"[:300])
        if cefr not in CEFR_LEVELS:
            raise SystemExit(f"Entry {i} ({vid}) has unknown CEFR {cefr!r}")
        if vid in seen:
            raise SystemExit(f"Duplicate id in source: {vid}")
        seen.add(vid)
        rows.append((
            vid, word,
            str(item.get("uk") or ""), str(item.get("us") or ""),
            json.dumps(item.get("senses") or [], ensure_ascii=False),
            json.dumps(item.get("ex") or [], ensure_ascii=False),
            list(item.get("col") or []), list(item.get("fam") or []),
            list(item.get("syn") or []), list(item.get("ant") or []),
            str(item.get("tip") or ""), cefr, topic,
            str(item.get("note") or ""), SOURCE, ATTRIBUTION,
        ))
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", required=True, help="Path to word-atlas.json")
    ap.add_argument("--dsn", default=None, help="Postgres DSN (must be mneme_test)")
    ap.add_argument("--env-file", default=None,
                    help="Optional .env file to read POSTGRES_PASSWORD from "
                         "(worktrees have no .env; the main checkout does)")
    args = ap.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    dsn = resolve_dsn(args.dsn, repo_root,
                      Path(args.env_file) if args.env_file else None)
    rows = load_rows(Path(args.json))
    print(f"input rows: {len(rows)} (unique ids: {len({r[0] for r in rows})})")

    try:
        import psycopg2
    except ImportError:
        try:
            import psycopg as psycopg2  # type: ignore[no-redef]
        except ImportError as exc:  # pragma: no cover
            raise SystemExit("Need psycopg2 or psycopg installed") from exc

    conn = psycopg2.connect(dsn)
    try:
        with conn.cursor() as cur:
            cur.execute(DDL)
            for start in range(0, len(rows), BATCH):
                cur.executemany(UPSERT, rows[start:start + BATCH])
            cur.execute("SELECT count(*) FROM vocab_units")
            total = cur.fetchone()[0]
            cur.execute(
                "SELECT cefr, count(*) FROM vocab_units "
                "GROUP BY cefr ORDER BY cefr")
            dist = dict(cur.fetchall())
            cur.execute(
                "SELECT count(*) FROM vocab_units "
                "WHERE attribution = %s", (ATTRIBUTION,))
            attributed = cur.fetchone()[0]
        conn.commit()
    finally:
        conn.close()
    print(f"vocab_units total after import: {total}")
    print(f"CEFR distribution: {dist}")
    print(f"rows with Word Atlas attribution: {attributed}")
    if total != len(rows) or attributed != len(rows):
        print("WARNING: total/attribution does not match input row count",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
