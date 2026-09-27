"""Joint final closure audit: K12 / ZHONGKAO / GAOKAO / NCE share one
canonical VocabularyItem authority. Read-only.

    python scripts/audit_english_learning_sources.py

Gates:
    K12/ZHONGKAO/GAOKAO/NCE_FINAL_AUDIT=PASS
    CANONICAL_VOCAB_AUTHORITY_COUNT=1
    CANONICAL_DUPLICATE_VOCAB=0
    CROSS_SOURCE_REUSE=PASS (NCE∩K12, NCE∩ZHONGKAO, NCE∩GAOKAO all > 0)
    OUT_OF_SCOPE_POLLUTION=0
    ORPHAN_MEMBERSHIPS=0
    BROKEN_FOREIGN_KEYS=0
    SOURCE_PROVENANCE_COVERAGE=100%
    LEARNING_EVENTS_IMPORT_POLLUTION=0
    FSRS_IMPORT_POLLUTION=0
    ALEMBIC_HEAD_COUNT=1
    TARGETED_TESTS=PASS
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
    result = {}

    async with SessionLocal() as db:
        # --- canonical authority count: vocabulary_items is the ONLY table with a
        # normalized_form column (the canonical lexical-authority marker). Relation
        # tables (memberships/occurrences) are not authorities. ---
        parallel = await _count(
            db,
            """
            SELECT count(*) FROM pg_tables t
            WHERE t.schemaname='public'
              AND t.tablename != 'vocabulary_items'
              AND EXISTS (
                  SELECT 1 FROM information_schema.columns c
                  WHERE c.table_name = t.tablename AND c.column_name = 'normalized_form'
              )
            """,
        )
        has_canonical = await _count(
            db,
            "SELECT count(*) FROM pg_tables WHERE schemaname='public' AND tablename='vocabulary_items'",
        )
        result["canonical_vocab_authority_count"] = 1 if (has_canonical == 1 and parallel == 0) else 0
        result["parallel_authority_tables"] = parallel

        # --- canonical duplicates ---
        result["canonical_duplicate_vocab"] = await _count(
            db,
            """
            SELECT count(*) FROM (
                SELECT language, normalized_form FROM vocabulary_items
                WHERE normalized_form IS NOT NULL
                GROUP BY language, normalized_form HAVING count(*) > 1
            ) sub
            """,
        )

        # --- per-source collection health ---
        for scope, key in (("K12_SYNC", "k12"), ("ZHONGKAO", "zhongkao"), ("GAOKAO", "gaokao")):
            dup = await _count(
                db,
                """
                SELECT count(*) FROM (
                    SELECT collection_id, vocabulary_item_id
                    FROM vocabulary_collection_memberships m
                    JOIN vocabulary_collections c ON c.id = m.collection_id
                    WHERE c.scope = :scope
                    GROUP BY collection_id, vocabulary_item_id HAVING count(*) > 1
                ) sub
                """,
                {"scope": scope},
            )
            orphan = await _count(
                db,
                """
                SELECT count(*) FROM vocabulary_collection_memberships m
                JOIN vocabulary_collections c ON c.id = m.collection_id
                LEFT JOIN vocabulary_items v ON v.id = m.vocabulary_item_id
                WHERE c.scope = :scope AND v.id IS NULL
                """,
                {"scope": scope},
            )
            out = await _count(
                db,
                """
                SELECT count(*) FROM vocabulary_collections
                WHERE scope = :scope AND (
                    source_relative_path ILIKE '%四级%' OR source_relative_path ILIKE '%六级%'
                    OR source_relative_path ILIKE '%考研%' OR source_relative_path ILIKE '%雅思%'
                    OR source_relative_path ILIKE '%托福%' OR source_relative_path ILIKE '%GRE%'
                    OR source_relative_path ILIKE '%SAT%' OR source_relative_path ILIKE '%专四%'
                    OR source_relative_path ILIKE '%专八%' OR source_relative_path ILIKE '%大学%'
                    OR source_relative_path ILIKE '%商务英语%' OR source_relative_path ILIKE '%新概念英语%'
                )
                """,
                {"scope": scope},
            )
            result[f"{key}_audit"] = "PASS" if (dup == 0 and orphan == 0 and out == 0) else "FAIL"

        # --- NCE audit ---
        nce_books = await _count(db, "SELECT count(*) FROM course_books")
        nce_lessons = await _count(db, "SELECT count(*) FROM lessons")
        nce_sentences = await _count(db, "SELECT count(*) FROM timed_sentences")
        nce_memberships = await _count(db, "SELECT count(*) FROM lesson_vocabulary_memberships")
        nce_orphan_mem = await _count(
            db,
            """
            SELECT count(*) FROM lesson_vocabulary_memberships m
            LEFT JOIN vocabulary_items v ON v.id = m.vocabulary_item_id
            LEFT JOIN lessons l ON l.id = m.lesson_id
            WHERE v.id IS NULL OR l.id IS NULL
            """,
        )
        nce_book_prov = await _count(
            db,
            "SELECT count(*) FROM course_books WHERE source_url IS NULL OR source_hash IS NULL",
        )
        nce_lesson_prov = await _count(
            db,
            "SELECT count(*) FROM lessons WHERE lrc_uri IS NULL OR lrc_hash IS NULL",
        )
        nce_ts_violations = await _count(
            db,
            """
            SELECT count(*) FROM timed_sentences a
            JOIN timed_sentences b ON b.lesson_id = a.lesson_id AND b.source_order = a.source_order + 1
            WHERE b.start_ms < a.start_ms
            """,
        )
        nce_neg_duration = await _count(
            db,
            "SELECT count(*) FROM timed_sentences WHERE end_ms IS NOT NULL AND end_ms <= start_ms",
        )
        nce_mem_dup = await _count(
            db,
            """
            SELECT count(*) FROM (
                SELECT lesson_id, vocabulary_item_id
                FROM lesson_vocabulary_memberships
                GROUP BY lesson_id, vocabulary_item_id HAVING count(*) > 1
            ) sub
            """,
        )
        result["nce_audit"] = (
            "PASS"
            if (
                nce_books == 8
                and nce_orphan_mem == 0
                and nce_book_prov == 0
                and nce_lesson_prov == 0
                and nce_ts_violations == 0
                and nce_neg_duration == 0
                and nce_mem_dup == 0
            )
            else "FAIL"
        )
        result["nce_counts"] = {
            "books": nce_books,
            "lessons": nce_lessons,
            "sentences": nce_sentences,
            "memberships": nce_memberships,
        }

        # --- cross-source reuse ---
        for scope, key in (("K12_SYNC", "k12"), ("ZHONGKAO", "zhongkao"), ("GAOKAO", "gaokao")):
            inter = await _count(
                db,
                """
                SELECT count(DISTINCT m.vocabulary_item_id)
                FROM lesson_vocabulary_memberships m
                JOIN vocabulary_collection_memberships cm
                  ON cm.vocabulary_item_id = m.vocabulary_item_id
                JOIN vocabulary_collections c ON c.id = cm.collection_id
                WHERE c.scope = :scope
                """,
                {"scope": scope},
            )
            result[f"nce_{key}_intersection"] = inter
        result["cross_source_reuse"] = (
            "PASS"
            if (
                result["nce_k12_intersection"] > 0
                and result["nce_zhongkao_intersection"] > 0
                and result["nce_gaokao_intersection"] > 0
            )
            else "FAIL"
        )

        # --- out-of-scope pollution (all sources) ---
        result["out_of_scope_pollution"] = await _count(
            db,
            """
            SELECT count(*) FROM vocabulary_collections
            WHERE source_relative_path ILIKE '%四级%' OR source_relative_path ILIKE '%六级%'
                OR source_relative_path ILIKE '%考研%' OR source_relative_path ILIKE '%雅思%'
                OR source_relative_path ILIKE '%托福%' OR source_relative_path ILIKE '%GRE%'
                OR source_relative_path ILIKE '%SAT%' OR source_relative_path ILIKE '%专四%'
                OR source_relative_path ILIKE '%专八%' OR source_relative_path ILIKE '%大学%'
                OR source_relative_path ILIKE '%商务英语%' OR source_relative_path ILIKE '%新概念英语%'
            """,
        )

        # --- orphan memberships (collection + lesson) ---
        result["orphan_memberships"] = await _count(
            db,
            """
            SELECT count(*) FROM (
                SELECT m.id FROM vocabulary_collection_memberships m
                LEFT JOIN vocabulary_items v ON v.id = m.vocabulary_item_id
                LEFT JOIN vocabulary_collections c ON c.id = m.collection_id
                WHERE v.id IS NULL OR c.id IS NULL
                UNION ALL
                SELECT m.id FROM lesson_vocabulary_memberships m
                LEFT JOIN vocabulary_items v ON v.id = m.vocabulary_item_id
                LEFT JOIN lessons l ON l.id = m.lesson_id
                WHERE v.id IS NULL OR l.id IS NULL
            ) sub
            """,
        )

        # --- broken foreign keys in the course chain ---
        result["broken_foreign_keys"] = await _count(
            db,
            """
            SELECT count(*) FROM (
                SELECT l.id FROM lessons l LEFT JOIN course_books b ON b.id = l.book_id WHERE b.id IS NULL
                UNION ALL
                SELECT t.id FROM timed_sentences t LEFT JOIN lessons l ON l.id = t.lesson_id WHERE l.id IS NULL
                UNION ALL
                SELECT o.id FROM sentence_vocabulary_occurrences o
                LEFT JOIN timed_sentences t ON t.id = o.sentence_id
                LEFT JOIN vocabulary_items v ON v.id = o.vocabulary_item_id
                WHERE t.id IS NULL OR v.id IS NULL
                UNION ALL
                SELECT m.id FROM lesson_vocabulary_memberships m
                LEFT JOIN timed_sentences t ON t.id = m.first_sentence_id
                WHERE m.first_sentence_id IS NOT NULL AND t.id IS NULL
            ) sub
            """,
        )

        # --- source provenance coverage ---
        k12_mem_total = await _count(db, "SELECT count(*) FROM vocabulary_collection_memberships")
        k12_mem_missing = await _count(
            db,
            "SELECT count(*) FROM vocabulary_collection_memberships WHERE source_relative_path IS NULL",
        )
        nce_book_total = await _count(db, "SELECT count(*) FROM course_books")
        nce_book_missing = await _count(
            db, "SELECT count(*) FROM course_books WHERE source_url IS NULL OR source_hash IS NULL"
        )
        nce_lesson_total = await _count(db, "SELECT count(*) FROM lessons")
        nce_lesson_missing = await _count(
            db, "SELECT count(*) FROM lessons WHERE lrc_uri IS NULL OR lrc_hash IS NULL"
        )
        total_rows = k12_mem_total + nce_book_total + nce_lesson_total
        missing_rows = k12_mem_missing + nce_book_missing + nce_lesson_missing
        result["source_provenance_coverage"] = (
            100 if total_rows > 0 and missing_rows == 0 else 0
        )

        # --- import pollution ---
        result["learning_events_import_pollution"] = await _count(
            db, "SELECT count(*) FROM learning_events"
        )
        # kc_mastery rows whose knowledge_point references NCE-created vocab would be
        # pollution; NCE import never writes kc_mastery, so any NCE-vocab KP is pollution.
        result["fsrs_import_pollution"] = await _count(
            db,
            """
            SELECT count(*) FROM kc_mastery
            WHERE knowledge_point LIKE 'vocab-%'
              AND substring(knowledge_point from 7) IN (
                  SELECT id FROM vocabulary_items WHERE source = 'nce'
              )
            """,
        )

    # --- alembic single head ---
    proc = subprocess.run(
        [sys.executable, "-m", "alembic", "heads"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    heads = [l for l in proc.stdout.splitlines() if "(head)" in l] if proc.returncode == 0 else []
    result["alembic_head_count"] = len(heads)

    # --- targeted tests ---
    test_proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_nce_importer.py",
            "tests/test_nce_import_db.py",
            "-q",
            "-p",
            "no:cacheprovider",
            "--no-cov",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    result["targeted_tests"] = "PASS" if test_proc.returncode == 0 else "FAIL"

    # --- joint gate ---
    gates = [
        result["k12_audit"] == "PASS",
        result["zhongkao_audit"] == "PASS",
        result["gaokao_audit"] == "PASS",
        result["nce_audit"] == "PASS",
        result["canonical_vocab_authority_count"] == 1,
        result["canonical_duplicate_vocab"] == 0,
        result["cross_source_reuse"] == "PASS",
        result["out_of_scope_pollution"] == 0,
        result["orphan_memberships"] == 0,
        result["broken_foreign_keys"] == 0,
        result["source_provenance_coverage"] == 100,
        result["learning_events_import_pollution"] == 0,
        result["fsrs_import_pollution"] == 0,
        result["alembic_head_count"] == 1,
        result["targeted_tests"] == "PASS",
    ]
    result["joint_final_audit"] = "PASS" if all(gates) else "FAIL"
    return result


async def _run() -> int:
    r = await audit()
    lines = [
        "TASK=MNEME_ENGLISH_LEARNING_SOURCES_FINAL_CLOSURE",
        "",
        f"K12_FINAL_AUDIT={r['k12_audit']}",
        f"ZHONGKAO_FINAL_AUDIT={r['zhongkao_audit']}",
        f"GAOKAO_FINAL_AUDIT={r['gaokao_audit']}",
        f"NCE_FINAL_AUDIT={r['nce_audit']}",
        "",
        f"CANONICAL_VOCAB_AUTHORITY_COUNT={r['canonical_vocab_authority_count']}",
        f"PARALLEL_AUTHORITY_TABLES={r['parallel_authority_tables']}",
        f"CANONICAL_DUPLICATE_VOCAB={r['canonical_duplicate_vocab']}",
        "",
        f"CROSS_SOURCE_REUSE={r['cross_source_reuse']}",
        f"NCE_K12_INTERSECTION={r['nce_k12_intersection']}",
        f"NCE_ZHONGKAO_INTERSECTION={r['nce_zhongkao_intersection']}",
        f"NCE_GAOKAO_INTERSECTION={r['nce_gaokao_intersection']}",
        "",
        f"OUT_OF_SCOPE_POLLUTION={r['out_of_scope_pollution']}",
        f"ORPHAN_MEMBERSHIPS={r['orphan_memberships']}",
        f"BROKEN_FOREIGN_KEYS={r['broken_foreign_keys']}",
        "",
        f"SOURCE_PROVENANCE_COVERAGE={r['source_provenance_coverage']}%",
        "",
        f"LEARNING_EVENTS_IMPORT_POLLUTION={r['learning_events_import_pollution']}",
        f"FSRS_IMPORT_POLLUTION={r['fsrs_import_pollution']}",
        "",
        f"ALEMBIC_HEAD_COUNT={r['alembic_head_count']}",
        "",
        f"TARGETED_TESTS={r['targeted_tests']}",
        "",
        f"JOINT_FINAL_AUDIT={r['joint_final_audit']}",
    ]
    report = "\n".join(lines)
    print(report)

    os.makedirs("reports", exist_ok=True)
    with open("reports/joint_final_audit.md", "w", encoding="utf-8") as fh:
        fh.write(report + "\n")
    with open("reports/joint_final_audit.json", "w", encoding="utf-8") as fh:
        json.dump(r, fh, indent=2, default=str)

    if r["joint_final_audit"] != "PASS":
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.parse_args()
    asyncio.run(_run())


if __name__ == "__main__":
    main()
