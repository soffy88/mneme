"""Runtime Echo-Loop transaction configuration contracts."""

from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, Field

from omodul._base import BaseConfig


class EchoLoopConfig(BaseConfig):
    _omodul_name: ClassVar[str] = "echo_loop_session"
    _omodul_version: ClassVar[str] = "1.0.0"
    _enabled_pillars: ClassVar[set[str]] = {"decision_trail", "cost", "fingerprint"}
    enable_blind_listen: bool = True
    enable_intensive_listen: bool = True
    enable_shadowing: bool = True
    enable_retell: bool = True
    passing_threshold: float = 0.6
    min_review_interval_hours: float = 1.0
    llm_model: str = "claude-sonnet-4-6"


class SpacedReviewConfig(BaseConfig):
    _omodul_name: ClassVar[str] = "spaced_review_schedule"
    _omodul_version: ClassVar[str] = "1.0.0"
    _enabled_pillars: ClassVar[set[str]] = {"decision_trail", "fingerprint"}
    review_intervals_hours: list[int] = Field(
        default_factory=lambda: [6, 24, 48, 96, 168, 336, 672]
    )
    max_reviews: int = 7


class DifficultSentenceConfig(BaseConfig):
    _omodul_name: ClassVar[str] = "difficult_sentence_archive"
    _omodul_version: ClassVar[str] = "1.0.0"
    _enabled_pillars: ClassVar[set[str]] = {"decision_trail", "cost"}


class ContextualFlashcardConfig(BaseConfig):
    _omodul_name: ClassVar[str] = "contextual_flashcard_generate"
    _omodul_version: ClassVar[str] = "1.0.0"
    _enabled_pillars: ClassVar[set[str]] = {"decision_trail", "cost"}
