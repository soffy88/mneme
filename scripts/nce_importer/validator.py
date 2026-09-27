"""NCEImportValidator: structural gates over the staging plan.

TIMESTAMP_ORDER_VIOLATIONS=0, NEGATIVE_DURATION=0, uniqueness of
(lesson_id, source_entry_key) and (lesson_id, vocabulary_item_id),
provenance completeness, and content-rights metadata.
"""

from dataclasses import dataclass, field
from typing import List, Optional

from .manifest import SourceManifest
from .planner import CourseImportPlan


@dataclass
class ValidationIssue:
    code: str
    detail: str


@dataclass
class ValidationReport:
    issues: List[ValidationIssue] = field(default_factory=list)

    @property
    def timestamp_order_violations(self) -> int:
        return sum(1 for i in self.issues if i.code == "TIMESTAMP_ORDER")

    @property
    def negative_duration(self) -> int:
        return sum(1 for i in self.issues if i.code in ("NEGATIVE_DURATION", "ZERO_DURATION"))

    @property
    def duplicate_sentences(self) -> int:
        return sum(1 for i in self.issues if i.code == "DUPLICATE_SENTENCE_KEY")

    @property
    def duplicate_memberships(self) -> int:
        return sum(1 for i in self.issues if i.code == "DUPLICATE_MEMBERSHIP")

    @property
    def missing_provenance(self) -> int:
        return sum(1 for i in self.issues if i.code == "MISSING_PROVENANCE")

    @property
    def ok(self) -> bool:
        return not self.issues


class NCEImportValidator:
    def validate(
        self, plan: CourseImportPlan, manifest: SourceManifest
    ) -> ValidationReport:
        report = ValidationReport()

        for book in plan.books:
            if not book.source_url or not book.source_hash:
                report.issues.append(
                    ValidationIssue("MISSING_PROVENANCE", f"book {book.book_key}")
                )
            for lesson in book.lessons:
                self._validate_lesson(lesson, report)

        self._validate_rights(manifest, report)
        return report

    def _validate_lesson(self, lesson, report: ValidationReport) -> None:
        if not lesson.lrc_uri or not lesson.lrc_hash:
            report.issues.append(
                ValidationIssue("MISSING_PROVENANCE", f"lesson {lesson.lesson_key} lrc")
            )
        if lesson.audio_uri and not lesson.audio_hash:
            report.issues.append(
                ValidationIssue(
                    "MISSING_PROVENANCE", f"lesson {lesson.lesson_key} audio hash"
                )
            )

        seen_keys = set()
        prev_start: Optional[int] = None
        for sent in lesson.sentences:
            if sent.source_entry_key in seen_keys:
                report.issues.append(
                    ValidationIssue(
                        "DUPLICATE_SENTENCE_KEY",
                        f"lesson {lesson.lesson_key} entry {sent.source_entry_key[:40]}",
                    )
                )
            seen_keys.add(sent.source_entry_key)

            if prev_start is not None and sent.start_ms < prev_start:
                report.issues.append(
                    ValidationIssue(
                        "TIMESTAMP_ORDER",
                        f"lesson {lesson.lesson_key} order {sent.source_order}",
                    )
                )
            prev_start = sent.start_ms

            if sent.end_ms is not None and sent.end_ms < sent.start_ms:
                report.issues.append(
                    ValidationIssue(
                        "NEGATIVE_DURATION",
                        f"lesson {lesson.lesson_key} order {sent.source_order}",
                    )
                )
            elif sent.end_ms is not None and sent.end_ms == sent.start_ms:
                report.issues.append(
                    ValidationIssue(
                        "ZERO_DURATION",
                        f"lesson {lesson.lesson_key} order {sent.source_order}",
                    )
                )

    def _validate_rights(
        self, manifest: SourceManifest, report: ValidationReport
    ) -> None:
        if manifest.content_rights != "RESTRICTED_EXTERNAL_EDUCATIONAL_CONTENT":
            report.issues.append(
                ValidationIssue(
                    "RIGHTS_METADATA",
                    f"content_rights={manifest.content_rights!r}",
                )
            )
        if manifest.redistribution_allowed:
            report.issues.append(
                ValidationIssue("RIGHTS_METADATA", "redistribution_allowed must be false")
            )
