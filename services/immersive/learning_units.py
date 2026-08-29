"""LearningUnit identity helpers (cross-media stable keys)."""

from __future__ import annotations

import re
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.immersive.memory_router import knowledge_ref_for_unit
from services.models import LearningUnit, LearningUnitOccurrence

_WORD = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?")
_STOP = frozenset(
    {
        "a",
        "an",
        "the",
        "and",
        "or",
        "but",
        "to",
        "of",
        "in",
        "on",
        "for",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "i",
        "you",
        "he",
        "she",
        "it",
        "we",
        "they",
        "me",
        "my",
        "your",
        "his",
        "her",
        "their",
        "this",
        "that",
        "with",
        "as",
        "at",
        "from",
        "by",
        "not",
        "no",
        "do",
        "did",
        "does",
        "have",
        "has",
        "had",
    }
)


def normalize_stable_key(text: str) -> str:
    tokens = [tok.casefold() for tok in _WORD.findall(text or "")]
    return "-".join(tokens) if tokens else "empty"


def extract_vocab_candidates(text: str, *, limit: int = 8) -> list[tuple[str, str]]:
    """Return (stable_key, surface_form) vocab candidates from a sentence."""

    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for match in _WORD.finditer(text or ""):
        surface = match.group(0)
        key = surface.casefold()
        if key in _STOP or len(key) < 3 or key in seen:
            continue
        seen.add(key)
        out.append((key, surface))
        if len(out) >= limit:
            break
    return out


def extract_phrase_candidates(text: str, *, limit: int = 3) -> list[tuple[str, str]]:
    """Very small MVP phrase extractor: contractions / 2-3 gram content phrases."""

    lowered = (text or "").casefold()
    phrases: list[tuple[str, str]] = []
    for pattern in (
        r"should(?:\s+have|'ve)",
        r"would(?:\s+have|'ve)",
        r"could(?:\s+have|'ve)",
        r"going to",
        r"have to",
        r"used to",
    ):
        match = re.search(pattern, lowered)
        if match:
            surface = match.group(0)
            phrases.append((normalize_stable_key(surface), surface))
    tokens = [t for t in _WORD.findall(text or "") if t.casefold() not in _STOP]
    if len(tokens) >= 2:
        bigram = " ".join(tokens[:2])
        phrases.append((normalize_stable_key(bigram), bigram))
    dedup: list[tuple[str, str]] = []
    seen: set[str] = set()
    for key, surface in phrases:
        if key in seen:
            continue
        seen.add(key)
        dedup.append((key, surface))
        if len(dedup) >= limit:
            break
    return dedup


async def get_or_create_learning_unit(
    db: AsyncSession,
    *,
    kind: str,
    stable_key: str,
    display_text: str,
    language: str | None = "en",
    metadata: dict[str, Any] | None = None,
) -> LearningUnit:
    existing = (
        await db.execute(
            select(LearningUnit).where(
                LearningUnit.kind == kind,
                LearningUnit.stable_key == stable_key,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    unit = LearningUnit(
        id=uuid.uuid4(),
        kind=kind,
        stable_key=stable_key,
        display_text=display_text,
        language=language,
        meta=metadata or {},
    )
    db.add(unit)
    await db.flush()
    return unit


async def link_occurrence(
    db: AsyncSession,
    *,
    learning_unit_id: uuid.UUID,
    media_id: uuid.UUID,
    segment_id: uuid.UUID,
    surface_form: str | None = None,
) -> LearningUnitOccurrence:
    existing = (
        await db.execute(
            select(LearningUnitOccurrence).where(
                LearningUnitOccurrence.learning_unit_id == learning_unit_id,
                LearningUnitOccurrence.segment_id == segment_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        if surface_form and not existing.surface_form:
            existing.surface_form = surface_form
        return existing
    row = LearningUnitOccurrence(
        id=uuid.uuid4(),
        learning_unit_id=learning_unit_id,
        media_id=media_id,
        segment_id=segment_id,
        surface_form=surface_form,
        meta={},
    )
    db.add(row)
    await db.flush()
    return row


async def ensure_units_for_segment(
    db: AsyncSession,
    *,
    media_id: uuid.UUID,
    segment_id: uuid.UUID,
    text: str,
    language: str | None = "en",
) -> list[dict[str, str]]:
    """Create VOCABULARY/PHRASE units + occurrences for a segment (MVP extractor)."""

    created: list[dict[str, str]] = []
    for key, surface in extract_vocab_candidates(text):
        unit = await get_or_create_learning_unit(
            db,
            kind="VOCABULARY",
            stable_key=key,
            display_text=surface,
            language=language,
        )
        await link_occurrence(
            db,
            learning_unit_id=unit.id,
            media_id=media_id,
            segment_id=segment_id,
            surface_form=surface,
        )
        created.append(
            {
                "learning_unit_id": str(unit.id),
                "kind": unit.kind,
                "stable_key": unit.stable_key,
                "knowledge_ref": knowledge_ref_for_unit(unit.kind, unit.stable_key),
            }
        )
    for key, surface in extract_phrase_candidates(text):
        unit = await get_or_create_learning_unit(
            db,
            kind="PHRASE",
            stable_key=key,
            display_text=surface,
            language=language,
        )
        await link_occurrence(
            db,
            learning_unit_id=unit.id,
            media_id=media_id,
            segment_id=segment_id,
            surface_form=surface,
        )
        created.append(
            {
                "learning_unit_id": str(unit.id),
                "kind": unit.kind,
                "stable_key": unit.stable_key,
                "knowledge_ref": knowledge_ref_for_unit(unit.kind, unit.stable_key),
            }
        )
    return created
