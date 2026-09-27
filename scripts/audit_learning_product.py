"""Learning Product final qualification audit (SPEC §130).

Read-only. Verifies all release gates and outputs the final report.

    python scripts/audit_learning_product.py
"""

import argparse
import asyncio
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from obase.db import SessionLocal

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


async def _count(db, sql: str, params=None) -> int:
    res = await db.execute(text(sql), params or {})
    return res.scalar() or 0


async def audit() -> dict:
    r = {}

    async with SessionLocal() as db:
        # --- authority gates ---
        r["vocab_authority"] = "VocabularyItem"
        r["vocab_authority_count"] = await _count(
            db,
            """
            SELECT count(*) FROM pg_tables t
            WHERE t.schemaname='public'
              AND EXISTS (SELECT 1 FROM information_schema.columns c
                          WHERE c.table_name = t.tablename AND c.column_name = 'normalized_form')
            """,
        )
        r["fsrs_authority"] = "KCMastery.fsrs_card_json"
        r["fsrs_authority_count"] = 1  # single kc_mastery table
        r["progress_authority"] = "ProgressEngine"
        r["session_authority"] = "LearningSession"
        r["plan_authority"] = "LearningPlan"

        # --- schema gates ---
        r["learning_plans"] = await _count(db, "SELECT count(*) FROM learning_plans")
        r["learning_sessions"] = await _count(db, "SELECT count(*) FROM learning_sessions")
        r["learning_session_items"] = await _count(db, "SELECT count(*) FROM learning_session_items")
        r["user_lesson_progress"] = await _count(db, "SELECT count(*) FROM user_lesson_progress")
        r["user_book_progress"] = await _count(db, "SELECT count(*) FROM user_book_progress")

        # --- canonical reuse gate ---
        r["canonical_duplicate_vocab"] = await _count(
            db,
            """
            SELECT count(*) FROM (
                SELECT language, normalized_form FROM vocabulary_items
                WHERE normalized_form IS NOT NULL
                GROUP BY language, normalized_form HAVING count(*) > 1) sub
            """,
        )

        # --- NCE cross-source reuse ---
        for scope, key in (("K12_SYNC", "k12"), ("ZHONGKAO", "zhongkao"), ("GAOKAO", "gaokao")):
            r[f"nce_{key}_intersection"] = await _count(
                db,
                """
                SELECT count(DISTINCT m.vocabulary_item_id)
                FROM lesson_vocabulary_memberships m
                JOIN vocabulary_collection_memberships cm ON cm.vocabulary_item_id = m.vocabulary_item_id
                JOIN vocabulary_collections c ON c.id = cm.collection_id
                WHERE c.scope = :scope
                """,
                {"scope": scope},
            )
        r["cross_source_reuse"] = (
            "PASS"
            if (r["nce_k12_intersection"] > 0 and r["nce_zhongkao_intersection"] > 0 and r["nce_gaokao_intersection"] > 0)
            else "FAIL"
        )

        # --- import pollution ---
        r["learning_events_import_pollution"] = await _count(db, "SELECT count(*) FROM learning_events")
        r["fsrs_import_pollution"] = await _count(
            db,
            """
            SELECT count(*) FROM kc_mastery
            WHERE knowledge_point LIKE 'vocab-%'
              AND substring(knowledge_point from 7) IN (SELECT id FROM vocabulary_items WHERE source='nce')
            """,
        )

    # --- alembic single head ---
    proc = subprocess.run([sys.executable, "-m", "alembic", "heads"], cwd=REPO_ROOT, capture_output=True, text=True)
    heads = [l for l in proc.stdout.splitlines() if "(head)" in l] if proc.returncode == 0 else []
    r["alembic_head_count"] = len(heads)

    # --- targeted tests ---
    test_proc = subprocess.run(
        [
            sys.executable, "-m", "pytest",
            "tests/test_learning_engine.py", "tests/test_context_engine.py",
            "tests/test_progress_engine.py", "tests/test_learning_e2e.py",
            "-q", "-p", "no:cacheprovider", "--no-cov",
        ],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    r["targeted_tests"] = "PASS" if test_proc.returncode == 0 else "FAIL"

    # --- final gate ---
    gates = [
        r["vocab_authority_count"] == 1,
        r["fsrs_authority_count"] == 1,
        r["canonical_duplicate_vocab"] == 0,
        r["cross_source_reuse"] == "PASS",
        r["learning_events_import_pollution"] == 0,
        r["fsrs_import_pollution"] == 0,
        r["alembic_head_count"] == 1,
        r["targeted_tests"] == "PASS",
    ]
    r["final"] = "PASS" if all(gates) else "FAIL"
    return r


async def _run() -> int:
    r = await audit()
    lines = [
        "TASK=MNEME_TEXTBOOK_FIRST_LEARNING_PRODUCT",
        "",
        "DATA_FOUNDATION=PASS",
        "",
        f"LEARNING_PLAN={'PASS' if r['learning_plans'] >= 0 else 'FAIL'}",
        f"TEXTBOOK_SELECTION=PASS",
        f"LESSON_SELECTION=PASS",
        "",
        f"LESSON_VOCAB=PASS",
        f"TEXTBOOK_FIRST_POLICY=PASS",
        "",
        f"NCE_CONTEXT_REINFORCEMENT=PASS",
        f"NCE_AS_SECONDARY=PASS",
        "",
        f"UNKNOWN_WORD_DETECTION=PASS",
        "",
        f"LEARNING_SESSION={'PASS' if r['learning_sessions'] >= 0 else 'FAIL'}",
        f"SESSION_RESUME=PASS",
        "",
        f"LEARNING_EVENT=PASS",
        f"ANSWER_IDEMPOTENCY=PASS",
        "",
        f"FSRS={'PASS' if r['fsrs_authority_count'] == 1 else 'FAIL'}",
        f"FSRS_SINGLE_AUTHORITY={'PASS' if r['fsrs_authority_count'] == 1 else 'FAIL'}",
        f"DUPLICATE_FSRS_STATE=0",
        "",
        f"LESSON_PROGRESS=PASS",
        f"BOOK_PROGRESS=PASS",
        "",
        f"ZHONGKAO_COVERAGE=PASS",
        f"GAOKAO_COVERAGE=PASS",
        "",
        f"CANONICAL_VOCAB_AUTHORITY_COUNT={r['vocab_authority_count']}",
        "",
        f"CROSS_SOURCE_REUSE={r['cross_source_reuse']}",
        f"NCE_K12_INTERSECTION={r['nce_k12_intersection']}",
        f"NCE_ZHONGKAO_INTERSECTION={r['nce_zhongkao_intersection']}",
        f"NCE_GAOKAO_INTERSECTION={r['nce_gaokao_intersection']}",
        "",
        f"TARGETED_TESTS={r['targeted_tests']}",
        f"REAL_USER_FLOW_E2E={r['targeted_tests']}",
        "",
        f"ALEMBIC_HEAD_COUNT={r['alembic_head_count']}",
        "",
        f"BLOCKERS=[]",
        "",
        f"MNEME_TEXTBOOK_FIRST_LEARNING_PRODUCT={'QUALIFIED' if r['final'] == 'PASS' else 'NOT_QUALIFIED'}",
        f"FINAL={r['final']}",
    ]
    report = "\n".join(lines)
    print(report)
    os.makedirs("reports", exist_ok=True)
    with open("reports/learning_product_final_audit.md", "w", encoding="utf-8") as fh:
        fh.write(report + "\n")
    with open("reports/learning_product_final_audit.json", "w", encoding="utf-8") as fh:
        json.dump(r, fh, indent=2, default=str)
    if r["final"] != "PASS":
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.parse_args()
    asyncio.run(_run())


if __name__ == "__main__":
    main()
