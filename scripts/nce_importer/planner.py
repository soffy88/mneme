"""CourseImportPlanner: builds the deterministic staging plan.

discover → fetch → parse → normalize → validate → staging plan
The plan is a pure function of the fetched source content: re-applying it
produces byte-identical entities (stable UUIDv5 ids), which is what makes
the second apply a no-op.
"""

import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from .audio import mp3_duration_ms
from .extractor import VocabularyExtractor
from .lrc import LRCParseResult, check_timestamp_order
from .manifest import NCE_SERIES, NCE_SCOPE, SourceManifest
from .normalizer import normalize_raw_text, normalize_sentence_text
from .resolver import CanonicalVocabularyResolver, ResolvedVocab

COURSE_ID_NS = uuid.NAMESPACE_URL


def _stable_id(namespace_seed: str) -> str:
    return str(uuid.uuid5(COURSE_ID_NS, namespace_seed))


@dataclass
class PlannedOccurrence:
    vocabulary_item_id: str
    normalized_form: str
    lexeme_type: str
    occurrence_index: int
    token_start: Optional[int]
    token_end: Optional[int]
    surface_form: str


@dataclass
class PlannedSentence:
    source_order: int
    start_ms: int
    end_ms: Optional[int]
    english_text: Optional[str]
    chinese_text: Optional[str]
    raw_text: Optional[str]
    source_line: Optional[int]
    source_entry_key: str
    occurrences: List[PlannedOccurrence] = field(default_factory=list)


@dataclass
class PlannedLesson:
    lesson_key: str
    title: str
    source_order: int
    audio_uri: Optional[str]
    audio_hash: Optional[str]
    audio_duration_ms: Optional[int]
    lrc_uri: Optional[str]
    lrc_hash: Optional[str]
    sentences: List[PlannedSentence] = field(default_factory=list)


@dataclass
class PlannedBook:
    book_key: str
    edition: str
    title: str
    level: Optional[str]
    source_url: Optional[str]
    source_hash: Optional[str]
    source_metadata: dict
    lessons: List[PlannedLesson] = field(default_factory=list)


@dataclass
class CourseImportPlan:
    scope: str
    series: str
    title: str
    source_id: Optional[str]
    books: List[PlannedBook]
    new_vocab: List[ResolvedVocab] = field(default_factory=list)

    @property
    def course_id(self) -> str:
        return _stable_id(f"mneme://course/{self.scope}/{self.series}")


@dataclass
class LessonFacts:
    """Intermediate per-lesson fetch/parse result."""

    lesson_key: str
    title: str
    source_order: int
    audio_uri: Optional[str]
    audio_hash: Optional[str]
    audio_duration_ms: Optional[int]
    lrc_uri: Optional[str]
    lrc_hash: Optional[str]
    lrc_parse: LRCParseResult
    audio_fetch_failed: bool = False


class CourseImportPlanner:
    def __init__(self, db: AsyncSession, resolver: CanonicalVocabularyResolver) -> None:
        self._db = db
        self._resolver = resolver

    async def build_plan(
        self,
        manifest: SourceManifest,
        parsed_books: List,
        lesson_facts: Dict[str, List[LessonFacts]],
    ) -> CourseImportPlan:
        await self._resolver.ensure_loaded()
        extractor = VocabularyExtractor(
            existing_phrases=set(self._resolver.existing_phrases)
        )

        plan = CourseImportPlan(
            scope=NCE_SCOPE,
            series=NCE_SERIES,
            title="New Concept English",
            source_id=manifest.source_repository,
            books=[],
        )
        new_vocab: Dict[str, ResolvedVocab] = {}

        for parsed in parsed_books:
            book_manifest = next(
                b for b in manifest.books if b.book_key == parsed.book_key
            )
            book_id = _stable_id(
                f"mneme://book/{NCE_SCOPE}/{NCE_SERIES}/{parsed.edition}/{parsed.book_key}"
            )
            planned_book = PlannedBook(
                book_key=parsed.book_key,
                edition=parsed.edition,
                title=parsed.name,
                level=parsed.level or None,
                source_url=book_manifest.book_resource_url,
                source_hash=parsed.book_json_sha256,
                source_metadata={
                    "cover": parsed.cover,
                    "units": len(parsed.units),
                    "book_json_url": book_manifest.book_json_url,
                    "content_rights": manifest.content_rights,
                    "redistribution_allowed": manifest.redistribution_allowed,
                    "code_license": manifest.code_license,
                    "source_commit": manifest.source_commit,
                },
                lessons=[],
            )

            for facts in lesson_facts[parsed.book_key]:
                planned_sentences = self._plan_sentences(facts, extractor, new_vocab)
                planned_book.lessons.append(
                    PlannedLesson(
                        lesson_key=facts.lesson_key,
                        title=facts.title,
                        source_order=facts.source_order,
                        audio_uri=facts.audio_uri,
                        audio_hash=facts.audio_hash,
                        audio_duration_ms=facts.audio_duration_ms,
                        lrc_uri=facts.lrc_uri,
                        lrc_hash=facts.lrc_hash,
                        sentences=planned_sentences,
                    )
                )

            plan.books.append(planned_book)

        plan.new_vocab = list(new_vocab.values())
        return plan

    def _plan_sentences(
        self,
        facts: LessonFacts,
        extractor: VocabularyExtractor,
        new_vocab: Dict[str, ResolvedVocab],
    ) -> List[PlannedSentence]:
        lines = facts.lrc_parse.lines
        planned: List[PlannedSentence] = []
        for idx, line in enumerate(lines):
            end_ms: Optional[int] = None
            if idx + 1 < len(lines):
                end_ms = lines[idx + 1].start_ms
            elif facts.audio_duration_ms is not None:
                end_ms = facts.audio_duration_ms

            english = normalize_sentence_text(line.english_text)
            chinese = (
                normalize_sentence_text(line.chinese_text)
                if line.chinese_text
                else None
            )
            raw = normalize_raw_text(line.raw_text)

            extraction = extractor.extract(english)
            occurrences: List[PlannedOccurrence] = []
            for occ_idx, occ in enumerate(extraction.occurrences):
                resolved = self._resolver_existing_or_new(
                    occ.normalized_form, occ.lexeme_type, occ.surface_form, new_vocab
                )
                occurrences.append(
                    PlannedOccurrence(
                        vocabulary_item_id=resolved.vocabulary_item_id,
                        normalized_form=occ.normalized_form,
                        lexeme_type=occ.lexeme_type,
                        occurrence_index=occ_idx,
                        token_start=occ.token_start,
                        token_end=occ.token_end,
                        surface_form=occ.surface_form,
                    )
                )

            planned.append(
                PlannedSentence(
                    source_order=idx + 1,
                    start_ms=line.start_ms,
                    end_ms=end_ms,
                    english_text=english or None,
                    chinese_text=chinese,
                    raw_text=raw,
                    source_line=line.source_line,
                    source_entry_key=raw[:200],
                    occurrences=occurrences,
                )
            )
        return planned

    def _resolver_existing_or_new(
        self,
        normalized_form: str,
        lexeme_type: str,
        surface_form: str,
        new_vocab: Dict[str, ResolvedVocab],
    ) -> ResolvedVocab:
        """Synchronous resolve against the pre-loaded resolver state."""
        existing_id = self._resolver.existing(normalized_form)
        if existing_id:
            return ResolvedVocab(
                normalized_form=normalized_form,
                lexeme_type=lexeme_type,
                vocabulary_item_id=existing_id,
                is_new=False,
                display_form=surface_form,
            )
        if normalized_form in new_vocab:
            return new_vocab[normalized_form]
        from .resolver import get_vid

        resolved = ResolvedVocab(
            normalized_form=normalized_form,
            lexeme_type=lexeme_type,
            vocabulary_item_id=get_vid(normalized_form),
            is_new=True,
            display_form=surface_form,
        )
        new_vocab[normalized_form] = resolved
        return resolved


def measure_audio_duration(audio_body: bytes) -> Optional[int]:
    return mp3_duration_ms(audio_body)


def validate_lrc_ordering(facts_list: List[LessonFacts]) -> List:
    violations = []
    for facts in facts_list:
        for i, j in check_timestamp_order(facts.lrc_parse.lines):
            violations.append((facts.lesson_key, facts.lrc_parse.lines[i].start_ms))
    return violations
