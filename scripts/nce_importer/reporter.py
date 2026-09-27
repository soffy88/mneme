"""NCEImportReporter: per-book + total qualification statistics."""

import json
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .planner import CourseImportPlan


@dataclass
class BookStats:
    book_key: str
    edition: str
    lessons: int = 0
    timed_sentences: int = 0
    unique_vocab: int = 0
    reused_existing_vocab: int = 0
    new_vocab: int = 0
    resource_failures: int = 0
    membership_rows: int = 0


@dataclass
class ImportReport:
    books: List[BookStats] = field(default_factory=list)
    resource_failures: int = 0
    blocked_resources: List[str] = field(default_factory=list)

    @property
    def total_lessons(self) -> int:
        return sum(b.lessons for b in self.books)

    @property
    def total_sentences(self) -> int:
        return sum(b.timed_sentences for b in self.books)

    @property
    def total_memberships(self) -> int:
        # Actual membership rows = distinct (lesson, vocabulary_item) pairs.
        return sum(b.membership_rows for b in self.books)

    @property
    def total_new_vocab(self) -> int:
        return sum(b.new_vocab for b in self.books)

    @property
    def total_reused_vocab(self) -> int:
        return sum(b.reused_existing_vocab for b in self.books)


class NCEImportReporter:
    def build(
        self,
        plan: CourseImportPlan,
        new_vocab_ids: set,
        resource_failures: int = 0,
        blocked_resources: Optional[List[str]] = None,
    ) -> ImportReport:
        report = ImportReport(
            resource_failures=resource_failures,
            blocked_resources=blocked_resources or [],
        )
        for book in plan.books:
            stats = BookStats(book_key=book.book_key, edition=book.edition)
            seen: set = set()
            for lesson in book.lessons:
                stats.lessons += 1
                stats.timed_sentences += len(lesson.sentences)
                lesson_vocab: set = set()
                for sent in lesson.sentences:
                    for occ in sent.occurrences:
                        seen.add(occ.vocabulary_item_id)
                        lesson_vocab.add(occ.vocabulary_item_id)
                stats.membership_rows += len(lesson_vocab)
            stats.unique_vocab = len(seen)
            stats.reused_existing_vocab = sum(
                1 for v in seen if v not in new_vocab_ids
            )
            stats.new_vocab = sum(1 for v in seen if v in new_vocab_ids)
            report.books.append(stats)
        return report

    async def cross_source_reuse(
        self, db: AsyncSession, plan: CourseImportPlan
    ) -> Dict[str, int]:
        """Count NCE vocabulary items that also appear in K12/ZHONGKAO/GAOKAO."""
        nce_vocab_ids = set()
        for book in plan.books:
            for lesson in book.lessons:
                for sent in lesson.sentences:
                    for occ in sent.occurrences:
                        nce_vocab_ids.add(occ.vocabulary_item_id)
        if not nce_vocab_ids:
            return {"k12": 0, "zhongkao": 0, "gaokao": 0}

        result = {}
        for scope, key in (
            ("K12_SYNC", "k12"),
            ("ZHONGKAO", "zhongkao"),
            ("GAOKAO", "gaokao"),
        ):
            query = text(
                """
                SELECT count(DISTINCT m.vocabulary_item_id)
                FROM vocabulary_collection_memberships m
                JOIN vocabulary_collections c ON c.id = m.collection_id
                WHERE c.scope = :scope AND m.vocabulary_item_id = ANY(:ids)
                """
            )
            res = await db.execute(
                query, {"scope": scope, "ids": list(nce_vocab_ids)}
            )
            result[key] = res.scalar() or 0
        return result

    def write(
        self,
        report: ImportReport,
        cross_source: Dict[str, int],
        output_dir: str,
        import_batch_id: str,
    ) -> Dict[str, str]:
        os.makedirs(output_dir, exist_ok=True)
        payload = {
            "import_batch_id": import_batch_id,
            "books": [
                {
                    "book_key": b.book_key,
                    "edition": b.edition,
                    "lessons": b.lessons,
                    "timed_sentences": b.timed_sentences,
                    "unique_vocab": b.unique_vocab,
                    "reused_existing_vocab": b.reused_existing_vocab,
                    "new_vocab": b.new_vocab,
                    "resource_failures": b.resource_failures,
                }
                for b in report.books
            ],
            "totals": {
                "books": len(report.books),
                "lessons": report.total_lessons,
                "sentences": report.total_sentences,
                "lesson_vocab_memberships": report.total_memberships,
                "new_vocab": report.total_new_vocab,
                "reused_vocab": report.total_reused_vocab,
                "resource_failures": report.resource_failures,
            },
            "cross_source_reuse": cross_source,
            "blocked_resources": report.blocked_resources,
        }
        json_path = os.path.join(output_dir, "nce_import_report.json")
        with open(json_path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False)

        lines = [
            "TASK=MNEME_NCE_COURSE_LEARNING_CHAIN",
            f"IMPORT_BATCH_ID={import_batch_id}",
            "",
        ]
        for b in report.books:
            lines += [
                f"BOOK={b.book_key} ({b.edition})",
                f"LESSONS={b.lessons}",
                f"TIMED_SENTENCES={b.timed_sentences}",
                f"UNIQUE_VOCAB={b.unique_vocab}",
                f"REUSED_EXISTING_VOCAB={b.reused_existing_vocab}",
                f"NEW_VOCAB={b.new_vocab}",
                f"RESOURCE_FAILURES={b.resource_failures}",
                "",
            ]
        lines += [
            f"NCE_BOOKS={len(report.books)}",
            f"NCE_LESSONS={report.total_lessons}",
            f"NCE_SENTENCES={report.total_sentences}",
            f"NCE_LESSON_VOCAB_MEMBERSHIPS={report.total_memberships}",
            f"NCE_REUSED_K12_VOCAB={cross_source.get('k12', 0)}",
            f"NCE_REUSED_ZHONGKAO_VOCAB={cross_source.get('zhongkao', 0)}",
            f"NCE_REUSED_GAOKAO_VOCAB={cross_source.get('gaokao', 0)}",
            f"RESOURCE_FAILURES={report.resource_failures}",
        ]
        md_path = os.path.join(output_dir, "nce_import_report.md")
        with open(md_path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
        return {"json": json_path, "md": md_path}
