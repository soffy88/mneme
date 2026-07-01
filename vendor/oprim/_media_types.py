"""Shared types for the video/audio ingestion batch."""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class VideoMeta:
    video_id: str
    title: str
    duration: float        # seconds; 0.0 if unavailable
    url: str
    upload_date: str | None   # YYYYMMDD
    description: str | None


@dataclass
class MediaResult:
    has_subtitle: bool
    subtitle_text: str | None
    audio_path: Path | None
    title: str
    duration: float
    metadata: dict    # uploader / upload_date / description


@dataclass
class TranscriptResult:
    text: str
    segments: list[dict]   # [{start, end, text}]
    language: str
    duration: float


@dataclass
class FilterRules:
    after_date: str | None = None
    limit: int | None = None
    min_duration: float | None = None
    max_duration: float | None = None
    title_include: list[str] = field(default_factory=list)
    title_exclude: list[str] = field(default_factory=list)
    llm_filter: str | None = None   # LLM smart-filter description


@dataclass
class MediaFindings:
    substrate_id: str
    title: str
    has_subtitle: bool
    transcribed: bool
    md_path: str | None


@dataclass
class SourceResult:
    """统一源订阅结果接口。各 xxx_search 元素返回此类型。"""
    external_id: str       # arxiv_id / gutenberg_id / oapen_handle
    title: str
    download_url: str      # PDF/epub/txt 直链
    file_type: str         # "pdf" | "epub" | "txt"
    metadata: dict         # authors/published/subjects/doi 等各源自填
