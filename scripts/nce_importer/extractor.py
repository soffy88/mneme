"""Deterministic vocabulary extractor: sentence → candidate lexical items.

Phase 1 scope: WORD always; PHRASE only when the n-gram matches an *existing*
canonical PHRASE VocabularyItem (loaded from DB). No n-gram is invented.
"""

import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Set

from .normalizer import normalize_vocab_token

TOKEN_RE = re.compile(r"[A-Za-z]+(?:['’\-][A-Za-z]+)*")


@dataclass
class TokenOccurrence:
    normalized_form: str
    lexeme_type: str  # WORD / PHRASE
    token_start: int
    token_end: int
    surface_form: str


@dataclass
class ExtractionResult:
    occurrences: List[TokenOccurrence]
    word_count: int
    phrase_count: int


class VocabularyExtractor:
    def __init__(self, existing_phrases: Optional[Set[str]] = None) -> None:
        self._existing_phrases: Set[str] = existing_phrases or set()

    def extract(self, english_text: str) -> ExtractionResult:
        tokens: List[tuple] = []  # (start, end, surface)
        for match in TOKEN_RE.finditer(english_text):
            tokens.append((match.start(), match.end(), match.group(0)))

        occurrences: List[TokenOccurrence] = []
        word_count = 0
        phrase_count = 0

        i = 0
        while i < len(tokens):
            phrase = None
            phrase_span = 0
            for n in (3, 2):
                if i + n <= len(tokens):
                    ngram = " ".join(
                        normalize_vocab_token(t[2]) for t in tokens[i : i + n]
                    )
                    if ngram in self._existing_phrases:
                        phrase = ngram
                        phrase_span = n
                        break
            if phrase is not None:
                start = tokens[i][0]
                end = tokens[i + phrase_span - 1][1]
                surface = english_text[start:end]
                occurrences.append(
                    TokenOccurrence(
                        normalized_form=phrase,
                        lexeme_type="PHRASE",
                        token_start=start,
                        token_end=end,
                        surface_form=surface,
                    )
                )
                phrase_count += 1
                i += phrase_span
            else:
                start, end, surface = tokens[i]
                norm = normalize_vocab_token(surface)
                if norm:
                    occurrences.append(
                        TokenOccurrence(
                            normalized_form=norm,
                            lexeme_type="WORD",
                            token_start=start,
                            token_end=end,
                            surface_form=surface,
                        )
                    )
                    word_count += 1
                i += 1

        return ExtractionResult(
            occurrences=occurrences,
            word_count=word_count,
            phrase_count=phrase_count,
        )


def load_existing_phrases(rows: List[Dict[str, str]]) -> Set[str]:
    return {r["normalized_form"] for r in rows if r.get("normalized_form")}
