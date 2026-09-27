"""Sentence normalization.

- english_text: Unicode NFKC, collapse whitespace, keep normal punctuation, no semantic change.
- raw_text: the untouched source line (after outer strip only).
- Vocabulary token normalization reuses the K12 VocabularyItem normalization
  (scripts/vocab_importer/normalizer.py) verbatim — no parallel rules.
"""

import re
import unicodedata

from scripts.vocab_importer.normalizer import get_lexeme_type, normalize_term

_WS_RE = re.compile(r"\s+")


def normalize_sentence_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = _WS_RE.sub(" ", text)
    return text.strip()


def normalize_raw_text(raw_line: str) -> str:
    return raw_line.strip()


def normalize_vocab_token(token: str) -> str:
    return normalize_term(token)


def get_vocab_lexeme_type(normalized_token: str) -> str:
    return get_lexeme_type(normalized_token)
