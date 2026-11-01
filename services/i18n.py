"""Minimal i18n infrastructure for the batch grafts (DeepTutor method subset).

Scope, pinned: zh/en only, covering ONLY the user-visible strings of the
nine new modules in this batch. Existing modules are untouched; frontend
translation is a follow-up. Every user-visible string in the new modules
goes through t(); the catalog test fails if any key lacks zh or en.
"""

from __future__ import annotations

SUPPORTED = ("zh", "en")
DEFAULT_LANG = "zh"

CATALOG: dict[str, dict[str, str]] = {
    # Shared
    "common.not_found": {"zh": "不存在", "en": "Not found"},
    "common.forbidden": {"zh": "无权访问", "en": "Forbidden"},
    # Video lessons
    "video_lesson.not_found": {"zh": "视频课规格不存在", "en": "Video lesson spec not found"},
    "video_lesson.create_forbidden": {"zh": "仅 admin 可创建视频课规格", "en": "Only admins can create video lesson specs"},
    "video_lesson.verify_forbidden": {"zh": "仅 admin 可验证视频课规格", "en": "Only admins can verify video lesson specs"},
    "video_lesson.duplicate_id": {"zh": "视频课 id 已存在", "en": "Video lesson id already exists"},
    "video_lesson.gate_failed": {"zh": "视频课规格未通过验证门", "en": "Video lesson spec failed verification"},
    # Citation check
    "citation_check.empty_segments": {"zh": "待核查分段不能为空", "en": "Segments to check must not be empty"},
    "citation_check.empty_ku_ids": {"zh": "ku_ids 不能为空", "en": "ku_ids must not be empty"},
    # Tasks / calendar
    "task.not_found": {"zh": "任务不存在", "en": "Task not found"},
    "task.invalid_payload": {"zh": "任务字段不合法", "en": "Invalid task fields"},
    "task.duplicate_id": {"zh": "任务 id 已存在", "en": "Task id already exists"},
    # Dictation
    "dictation.not_found": {"zh": "听写规格不存在", "en": "Dictation spec not found"},
    "dictation.create_forbidden": {"zh": "仅 admin 可创建听写规格", "en": "Only admins can create dictation specs"},
    "dictation.verify_forbidden": {"zh": "仅 admin 可验证听写规格", "en": "Only admins can verify dictation specs"},
    "dictation.duplicate_id": {"zh": "听写规格 id 已存在", "en": "Dictation spec id already exists"},
    "dictation.gate_failed": {"zh": "听写规格未通过验证门", "en": "Dictation spec failed verification"},
    "dictation.attempt_not_found": {"zh": "听写记录不存在", "en": "Dictation attempt not found"},
    # Shadowing
    "shadowing.not_found": {"zh": "跟读规格不存在", "en": "Shadowing spec not found"},
    "shadowing.create_forbidden": {"zh": "仅 admin 可创建跟读规格", "en": "Only admins can create shadowing specs"},
    "shadowing.verify_forbidden": {"zh": "仅 admin 可验证跟读规格", "en": "Only admins can verify shadowing specs"},
    "shadowing.duplicate_id": {"zh": "跟读规格 id 已存在", "en": "Shadowing spec id already exists"},
    "shadowing.gate_failed": {"zh": "跟读规格未通过验证门", "en": "Shadowing spec failed verification"},
    "shadowing.invalid_sentence": {"zh": "句子序号越界", "en": "Sentence index out of range"},
    "shadowing.empty_audio": {"zh": "音频不能为空", "en": "Audio must not be empty"},
    # Graded audio
    "graded_audio.not_found": {"zh": "分级有声规格不存在", "en": "Graded audio spec not found"},
    "graded_audio.create_forbidden": {"zh": "仅 admin 可创建分级有声规格", "en": "Only admins can create graded audio specs"},
    "graded_audio.verify_forbidden": {"zh": "仅 admin 可验证分级有声规格", "en": "Only admins can verify graded audio specs"},
    "graded_audio.duplicate_id": {"zh": "分级有声规格 id 已存在", "en": "Graded audio spec id already exists"},
    "graded_audio.gate_failed": {"zh": "分级有声规格未通过验证门", "en": "Graded audio spec failed verification"},
    # Mock exams
    "mock_exam.not_found": {"zh": "模考规格不存在", "en": "Mock exam spec not found"},
    "mock_exam.create_forbidden": {"zh": "仅 admin 可创建模考规格", "en": "Only admins can create mock exam specs"},
    "mock_exam.verify_forbidden": {"zh": "仅 admin 可验证模考规格", "en": "Only admins can verify mock exam specs"},
    "mock_exam.duplicate_id": {"zh": "模考规格 id 已存在", "en": "Mock exam spec id already exists"},
    "mock_exam.gate_failed": {"zh": "模考规格未通过验证门", "en": "Mock exam spec failed verification"},
    "mock_exam.attempt_not_found": {"zh": "模考记录不存在", "en": "Mock exam attempt not found"},
    "mock_exam.answers_mismatch": {"zh": "作答须覆盖全部题目", "en": "Answers must cover every question"},
}


def _normalize(code: str | None) -> str | None:
    if not code:
        return None
    primary = code.strip().lower().replace("_", "-").split("-")[0]
    return primary if primary in SUPPORTED else None


def negotiate_language(accept_language: str | None, lang: str | None = None) -> str:
    """Pick zh/en: explicit lang wins, then Accept-Language q order, else zh."""
    explicit = _normalize(lang)
    if explicit is not None:
        return explicit
    if accept_language:
        parts: list[tuple[float, str]] = []
        for raw in accept_language.split(","):
            chunk = raw.strip()
            if not chunk:
                continue
            if ";q=" in chunk:
                lang_part, q_part = chunk.split(";q=", 1)
                try:
                    q = float(q_part.strip())
                except ValueError:
                    q = 0.0
            else:
                lang_part, q = chunk, 1.0
            norm = _normalize(lang_part)
            if norm is not None and q > 0:
                parts.append((q, norm))
        if parts:
            parts.sort(key=lambda item: -item[0])
            return parts[0][1]
    return DEFAULT_LANG


def t(key: str, lang: str | None = None, **kwargs: object) -> str:
    """Look up a user-visible string; zh fallback, then the key itself."""
    entry = CATALOG.get(key)
    if entry is None:
        return key
    lang_norm = _normalize(lang) or DEFAULT_LANG
    text = entry.get(lang_norm) or entry.get(DEFAULT_LANG) or key
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            return text
    return text


__all__ = ["CATALOG", "DEFAULT_LANG", "SUPPORTED", "negotiate_language", "t"]
