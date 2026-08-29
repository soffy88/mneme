"""Canonical Immersive Learning constants (MVP)."""

from __future__ import annotations

from enum import Enum

IMMERSIVE_SOURCE = "immersive_player"
IMMERSIVE_PRACTICE_SOURCE = "media_practice"

# Scaffold L0–L5 (Policy owns recommendation; player renders / overrides).
SCAFFOLD_LEVELS = frozenset({0, 1, 2, 3, 4, 5})

SCAFFOLD_LABELS = {
    0: "bilingual",
    1: "target_subtitle",
    2: "keyword_hints",
    3: "no_subtitle",
    4: "active_recall",
    5: "delayed_transfer",
}

MEDIA_TYPES = frozenset({"VIDEO", "AUDIO"})
SOURCE_TYPES = frozenset({"USER_UPLOAD", "OBJECT_STORAGE"})
CONTENT_PROVENANCE = frozenset(
    {"USER_UPLOADED", "USER_OWNED", "LICENSED", "PUBLIC", "EXTERNAL_REFERENCE"}
)
LEARNING_UNIT_KINDS = frozenset(
    {
        "VOCABULARY",
        "PHRASE",
        "GRAMMAR_PATTERN",
        "LISTENING_FEATURE",
        "CONCEPT",
    }
)

# LearningEvent v2 action vocabulary for immersive MVP.
IMMERSIVE_ACTIONS = frozenset(
    {
        "segment_replayed",
        "subtitle_shown",
        "subtitle_hidden",
        "translation_revealed",
        "vocab_lookup",
        "listening_attempt",
        "listening_result",
        "dictation_attempt",
        "dictation_result",
        "comprehension_attempt",
        "comprehension_result",
        "sentence_recall_attempt",
        "sentence_recall_result",
        "scaffold_level_changed",
        "transfer_attempt",
        "transfer_result",
    }
)

PERFORMANCE_RESULT_ACTIONS = frozenset(
    {
        "listening_result",
        "dictation_result",
        "comprehension_result",
        "sentence_recall_result",
        "transfer_result",
    }
)

BEHAVIORAL_ACTIONS = frozenset(
    {
        "segment_replayed",
        "subtitle_shown",
        "subtitle_hidden",
        "translation_revealed",
        "vocab_lookup",
        "scaffold_level_changed",
    }
)

PERFORMANCE_ACTIONS = PERFORMANCE_RESULT_ACTIONS | frozenset(
    {
        "listening_attempt",
        "dictation_attempt",
        "comprehension_attempt",
        "sentence_recall_attempt",
        "transfer_attempt",
    }
)

# Evidence strength classes.
EVIDENCE_STRENGTH_NONE = "none"
EVIDENCE_STRENGTH_WEAK_BEHAVIORAL = "weak_behavioral"
EVIDENCE_STRENGTH_PERFORMANCE = "performance"

MEMORY_ACTIONS = frozenset(
    {
        "NO_MEMORY_ACTION",
        "CREATE_MEMORY",
        "UPDATE_MEMORY",
        "REVIEW_MEMORY",
    }
)

POLICY_ACTIONS = frozenset(
    {
        "RECOMMEND_SCAFFOLD_LEVEL",
        "RECOMMEND_LISTENING_PRACTICE",
        "RECOMMEND_DICTATION",
        "RECOMMEND_COMPREHENSION_CHECK",
        "RECOMMEND_RECALL",
        "RECOMMEND_TRANSFER",
        "VIDEO_SEGMENT_TASK",
        "LISTENING_TASK",
        "DICTATION_TASK",
        "COMPREHENSION_TASK",
        "RECALL_TASK",
        "TRANSFER_TASK",
    }
)

MEDIA_ALLOWED_EXTENSIONS = {".mp4", ".webm", ".mp3", ".m4a", ".wav"}
MEDIA_CONTENT_TYPES = {
    ".mp4": {"video/mp4", "application/octet-stream"},
    ".webm": {"video/webm", "application/octet-stream"},
    ".mp3": {"audio/mpeg", "audio/mp3", "application/octet-stream"},
    ".m4a": {"audio/mp4", "audio/m4a", "application/octet-stream"},
    ".wav": {"audio/wav", "audio/x-wav", "application/octet-stream"},
}
SUBTITLE_ALLOWED_EXTENSIONS = {".srt", ".vtt"}

DEFAULT_MAX_MEDIA_BYTES = 200 * 1024 * 1024  # 200 MiB
DEFAULT_MAX_SUBTITLE_BYTES = 2 * 1024 * 1024  # 2 MiB SRT/VTT cap


class TelemetryEventType(str, Enum):
    PLAY = "play"
    PAUSE = "pause"
    SEEK = "seek"
    SPEED = "speed"
    SEGMENT_ENTER = "segment_enter"
