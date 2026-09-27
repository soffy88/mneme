"""NCE course learning chain importer — official CLI entry.

    python scripts/import_nce_course.py --dry-run
    python scripts/import_nce_course.py --apply
    python scripts/import_nce_course.py --apply --edition 1985
    python scripts/import_nce_course.py --apply --book NCE2
    python scripts/import_nce_course.py --manifest scripts/nce_importer/pinned_manifest.json

Pipeline: discover → fetch → parse → normalize → validate → staging plan →
DB transaction → upsert → qualification → commit. Fatal failure rolls back.
"""

import argparse
import asyncio
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import services  # noqa: F401 — must run first: registers vendor/ on sys.path
from obase.db import SessionLocal
from services.models import VocabularyImportBatch

from scripts.nce_importer.fetch import ResourceFetcher
from scripts.nce_importer.manifest import BookManifestParser, NCEManifestLoader
from scripts.nce_importer.planner import (
    CourseImportPlanner,
    LessonFacts,
    measure_audio_duration,
)
from scripts.nce_importer.repository import CourseImportRepository
from scripts.nce_importer.reporter import NCEImportReporter
from scripts.nce_importer.resolver import CanonicalVocabularyResolver
from scripts.nce_importer.validator import NCEImportValidator


async def run_async(args) -> int:
    manifest = NCEManifestLoader().load(args.manifest)
    if args.source_commit:
        manifest.source_commit = args.source_commit

    books = manifest.books
    if args.edition:
        books = [b for b in books if b.edition == args.edition]
    if args.book:
        books = [b for b in books if b.book_key == args.book]
    if not books:
        print("No books selected.")
        return 2

    print(f"source_repository={manifest.source_repository}")
    print(f"source_commit={manifest.source_commit}")
    print(f"books={[b.book_key + ':' + b.edition for b in books]}")

    fetcher = ResourceFetcher(concurrency=args.concurrency)
    parser = BookManifestParser(fetcher)

    parsed_books = []
    blocked_resources = []
    for book in books:
        try:
            parsed = await parser.parse(book)
            parsed_books.append(parsed)
            print(f"book {book.book_key} ({book.edition}): {len(parsed.units)} units")
        except Exception as exc:  # noqa: BLE001 - reported verbatim, never faked
            blocked_resources.append(f"{book.book_json_url}: {exc}")
            print(f"book {book.book_key} ({book.edition}): BOOK_FETCH_FAILED {exc}")

    # Fetch LRC + MP3 for every lesson of every parsed book.
    fetch_urls = []
    url_meta = []  # (url, book_key, unit_filename, kind)
    for book, parsed in zip(books, parsed_books):
        for unit in parsed.units:
            audio_url = book.audio_url.replace("{filename}", unit.filename)
            lrc_url = book.lrc_url.replace("{filename}", unit.filename)
            fetch_urls.extend([audio_url, lrc_url])
            url_meta.append((audio_url, book.book_key, unit.filename, "audio"))
            url_meta.append((lrc_url, book.book_key, unit.filename, "lrc"))

    print(f"fetching {len(fetch_urls)} resources "
          f"({sum(1 for m in url_meta if m[3]=='lrc')} lrc, "
          f"{sum(1 for m in url_meta if m[3]=='audio')} audio) ...")
    fetch_report = await fetcher.fetch_all(fetch_urls)
    by_url = {r.url: r for r in fetch_report.ok}
    for fail in fetch_report.failed:
        blocked_resources.append(f"{fail.url}: {fail.reason}")
    print(f"fetched={len(fetch_report.ok)} failed={fetch_report.failure_count}")

    # Build per-lesson facts.
    lesson_facts: dict = {p.book_key: [] for p in parsed_books}
    for book, parsed in zip(books, parsed_books):
        for unit in parsed.units:
            audio_url = book.audio_url.replace("{filename}", unit.filename)
            lrc_url = book.lrc_url.replace("{filename}", unit.filename)
            audio_res = by_url.get(audio_url)
            lrc_res = by_url.get(lrc_url)

            audio_hash = audio_res.sha256 if audio_res else None
            audio_duration_ms = measure_audio_duration(audio_res.body) if audio_res else None
            lrc_hash = lrc_res.sha256 if lrc_res else None

            lrc_parse = None
            if lrc_res:
                from scripts.nce_importer.lrc import parse_lrc

                lrc_parse = parse_lrc(lrc_res.body.decode("utf-8"))

            facts = LessonFacts(
                lesson_key=unit.filename,
                title=unit.title,
                source_order=unit.source_order,
                audio_uri=audio_url,
                audio_hash=audio_hash,
                audio_duration_ms=audio_duration_ms,
                lrc_uri=lrc_url,
                lrc_hash=lrc_hash,
                lrc_parse=lrc_parse,
                audio_fetch_failed=audio_res is None,
            )
            lesson_facts[parsed.book_key].append(facts)

    new_vocab_ids: set = set()
    plan = None
    async with SessionLocal() as db:
        resolver = CanonicalVocabularyResolver(db)
        planner = CourseImportPlanner(db, resolver)
        plan = await planner.build_plan(manifest, parsed_books, lesson_facts)
        new_vocab_ids = {v.vocabulary_item_id for v in plan.new_vocab}

    validator = NCEImportValidator()
    validation = validator.validate(plan, manifest)
    print(f"validation: issues={len(validation.issues)} "
          f"timestamp_order_violations={validation.timestamp_order_violations} "
          f"negative_duration={validation.negative_duration}")
    for issue in validation.issues[:20]:
        print(f"  ISSUE {issue.code}: {issue.detail}")

    reporter = NCEImportReporter()
    report = reporter.build(
        plan,
        new_vocab_ids,
        resource_failures=fetch_report.failure_count + len(blocked_resources),
        blocked_resources=blocked_resources,
    )

    mode = "APPLY" if args.apply else "DRY_RUN"
    print(f"\n=== {mode} REPORT ===")
    for b in report.books:
        print(f"BOOK={b.book_key} ({b.edition})")
        print(f"LESSONS={b.lessons}")
        print(f"TIMED_SENTENCES={b.timed_sentences}")
        print(f"UNIQUE_VOCAB={b.unique_vocab}")
        print(f"REUSED_EXISTING_VOCAB={b.reused_existing_vocab}")
        print(f"NEW_VOCAB={b.new_vocab}")
        print(f"RESOURCE_FAILURES={b.resource_failures}")
    print(f"NCE_BOOKS={len(report.books)}")
    print(f"NCE_LESSONS={report.total_lessons}")
    print(f"NCE_SENTENCES={report.total_sentences}")
    print(f"NCE_LESSON_VOCAB_MEMBERSHIPS={report.total_memberships}")

    if not args.apply:
        if validation.issues:
            print("VALIDATION_FAILED — fix issues before apply.")
            return 1
        print("Dry run complete (no writes).")
        return 0

    if validation.issues:
        print("VALIDATION_FAILED — rolling back, no writes.")
        return 1

    # Apply: single transaction, rollback on fatal failure.
    import uuid as _uuid

    batch_id = str(_uuid.uuid4())
    async with SessionLocal() as db:
        try:
            repo = CourseImportRepository(db)
            stats = await repo.execute(plan)
            batch = VocabularyImportBatch(
                id=batch_id,
                source_name=manifest.source_repository,
                source_commit_sha=manifest.source_commit,
                parser_version=manifest.parser_version,
                mode="APPLY",
                status="SUCCESS",
                vocab_created=stats.vocab_created,
                vocab_existing=stats.vocab_existing,
                report_path=f"reports/nce_import_report.json",
            )
            db.add(batch)
            await db.commit()
        except Exception as exc:  # noqa: BLE001
            await db.rollback()
            print(f"APPLY_FAILED (rolled back): {type(exc).__name__}: {exc}")
            return 1

    # Qualification: cross-source reuse (needs its own read session).
    async with SessionLocal() as db:
        cross = await reporter.cross_source_reuse(db, plan)
    paths = reporter.write(report, cross, args.report_dir, batch_id)
    print(f"NCE_REUSED_K12_VOCAB={cross.get('k12', 0)}")
    print(f"NCE_REUSED_ZHONGKAO_VOCAB={cross.get('zhongkao', 0)}")
    print(f"NCE_REUSED_GAOKAO_VOCAB={cross.get('gaokao', 0)}")
    print(f"Apply complete. Report: {paths['json']}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="NCE course learning chain importer")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--edition", default=None)
    parser.add_argument("--book", default=None)
    parser.add_argument("--manifest", default=None)
    parser.add_argument("--source-commit", default=None)
    parser.add_argument("--report-dir", default="reports")
    parser.add_argument("--concurrency", type=int, default=8)
    args = parser.parse_args()
    if not args.dry_run and not args.apply:
        print("Specify --dry-run or --apply.")
        raise SystemExit(2)
    raise SystemExit(asyncio.run(run_async(args)))


if __name__ == "__main__":
    main()
