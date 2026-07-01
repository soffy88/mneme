"""P-4: rubric_score — pure-computation multi-dimension essay scoring.

No LLM. All scores are derived from statistical text features (character count,
paragraph structure, sentence variety, punctuation density).
"""

from __future__ import annotations

import re


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def rubric_score(
    essay_text: str,
    *,
    rubric: dict[str, float],
    grade_level: str,
    essay_type: str,
) -> dict[str, float]:
    """Score an essay against rubric dimensions using statistical text features.

    All scoring is deterministic and purely computational — no LLM.

    Args:
        essay_text: Full essay body as a string.
        rubric: {dimension_name: weight} mapping. Weights are caller's responsibility;
                they need not sum to 1.0 and are not normalised here.
        grade_level: Student grade label (e.g. "高中", "初中"). Used to calibrate
                     expected length thresholds.
        essay_type: Essay genre (e.g. "议论文", "记叙文"). Informs structure expectations.

    Returns:
        {dimension_name: score_0_to_100} for every key in rubric.

    Raises:
        ValueError: rubric is empty.
    """
    if not rubric:
        raise ValueError("rubric must not be empty")

    if not essay_text.strip():
        return {dim: 0.0 for dim in rubric}

    scores: dict[str, float] = {}
    for dim in rubric:
        scores[dim] = _score_dimension(dim, essay_text, grade_level, essay_type)
    return scores


# ---------------------------------------------------------------------------
# Dimension dispatchers
# ---------------------------------------------------------------------------

_DIM_ALIASES: dict[str, str] = {
    "结构": "structure",
    "structure": "structure",
    "立意": "theme",
    "theme": "theme",
    "语言": "language",
    "language": "language",
    "格式": "format",
    "format": "format",
}


def _score_dimension(dim: str, text: str, grade_level: str, essay_type: str) -> float:
    key = _DIM_ALIASES.get(dim, "generic")
    if key == "structure":
        return _score_structure(text, essay_type)
    if key == "theme":
        return _score_theme(text, grade_level)
    if key == "language":
        return _score_language(text)
    if key == "format":
        return _score_format(text)
    return _score_generic(text)


# ---------------------------------------------------------------------------
# Individual scorers (0–100)
# ---------------------------------------------------------------------------

def _paragraphs(text: str) -> list[str]:
    paras = [p.strip() for p in re.split(r"\n{2,}|\n(?=\s)", text) if p.strip()]
    if not paras:
        paras = [text.strip()]
    return paras


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"[。！？!?]+", text) if s.strip()]


def _score_structure(text: str, essay_type: str) -> float:
    """Score based on paragraph count relative to the expected range."""
    paras = _paragraphs(text)
    n = len(paras)

    # Expected ranges vary by type
    if "议论" in essay_type:
        ideal_lo, ideal_hi = 3, 5
    elif "记叙" in essay_type:
        ideal_lo, ideal_hi = 4, 7
    else:
        ideal_lo, ideal_hi = 3, 6

    if ideal_lo <= n <= ideal_hi:
        base = 85.0
    elif n < ideal_lo:
        base = max(30.0, 85.0 - (ideal_lo - n) * 15.0)
    else:
        base = max(60.0, 85.0 - (n - ideal_hi) * 8.0)

    # Bonus: first and last paragraph non-trivially present
    if len(paras[0]) >= 20 and len(paras[-1]) >= 20:
        base = min(100.0, base + 5.0)

    return round(base, 1)


def _score_theme(text: str, grade_level: str) -> float:
    """Score based on vocabulary richness and length adequacy."""
    chars = re.findall(r"[一-鿿]", text)
    total = len(chars)
    if total == 0:
        # Fallback for non-Chinese text
        words = text.split()
        total = len(words)
        unique = len(set(w.lower() for w in words))
    else:
        unique = len(set(chars))

    ttr = unique / total if total else 0.0

    # Grade-calibrated length thresholds
    if "高中" in grade_level or "高三" in grade_level:
        expected_lo, expected_hi = 600, 1200
    elif "初中" in grade_level or "初三" in grade_level:
        expected_lo, expected_hi = 400, 900
    else:
        expected_lo, expected_hi = 200, 600

    # Length score
    if expected_lo <= total <= expected_hi:
        length_score = 90.0
    elif total < expected_lo:
        length_score = max(40.0, 90.0 * total / expected_lo)
    else:
        # Too long isn't penalised harshly
        length_score = max(70.0, 90.0 - (total - expected_hi) / 100 * 5)

    # TTR score (higher is richer vocabulary)
    ttr_score = min(100.0, ttr * 200)

    return round(0.5 * length_score + 0.5 * ttr_score, 1)


def _score_language(text: str) -> float:
    """Score based on sentence variety (count and length variance)."""
    sents = _sentences(text)
    n = len(sents)
    if n == 0:
        return 0.0

    lengths = [len(s) for s in sents]
    mean_len = sum(lengths) / n

    if n < 2:
        variance = 0.0
    else:
        variance = sum((l - mean_len) ** 2 for l in lengths) / n

    # Sentence count component
    count_score = min(100.0, n * 5.0)  # 20 sentences → full

    # Variety component (higher variance = more varied sentence structure)
    variety_score = min(100.0, (variance ** 0.5) * 5.0)

    return round(0.5 * count_score + 0.5 * variety_score, 1)


def _score_format(text: str) -> float:
    """Score based on punctuation density, paragraph breaks, and total length."""
    score = 50.0

    # Chinese punctuation presence
    punc = len(re.findall(r"[，。！？、；：""''（）【】《》]", text))
    total_chars = len(text)
    punc_ratio = punc / total_chars if total_chars else 0.0
    if punc_ratio >= 0.05:
        score += 20.0
    elif punc_ratio >= 0.02:
        score += 10.0

    # Has paragraph breaks
    if "\n" in text:
        score += 15.0

    # Appropriate total length (not too short)
    if total_chars >= 200:
        score += 15.0
    elif total_chars >= 100:
        score += 7.0

    return round(min(100.0, score), 1)


def _score_generic(text: str) -> float:
    """Fallback scorer for unrecognised dimension names."""
    chars = len(text.strip())
    if chars >= 500:
        return 75.0
    return round(min(75.0, chars / 500 * 75), 1)
