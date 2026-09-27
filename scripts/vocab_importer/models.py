from dataclasses import dataclass
from typing import Optional, List, Dict, Any

@dataclass
class ParsedVocabularyEntry:
    term: str
    phonetic_uk: Optional[str]
    phonetic_us: Optional[str]
    phonetic_generic: Optional[str]
    definition_raw: Optional[str]
    pos: Optional[str]
    sentence: Optional[str]
    source_row: int
    source_order: int
    raw_values: Dict[str, Any]

@dataclass
class VocabularyCollectionMeta:
    kind: str
    scope: str
    title: str
    publisher: Optional[str]
    stage: str
    grade: Optional[int]
    semester: Optional[int]
    edition: Optional[str]
    curriculum_year: Optional[int]
    book_type: Optional[str]
    exam_type: Optional[str]
    region: Optional[str]
    source_relative_path: str
    source_file_sha256: str
