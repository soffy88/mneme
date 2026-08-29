"""Security-focused Immersive Learning tests."""

from __future__ import annotations

import pytest

from services.immersive.transcript_parser import TranscriptParseError, parse_srt
from services.upload_safety import UploadValidationError, validate_filename


def test_path_traversal_filename_rejected() -> None:
    with pytest.raises(UploadValidationError):
        validate_filename("../etc/passwd.mp4", allowed_extensions={".mp4"})
    with pytest.raises(UploadValidationError):
        validate_filename("/abs/path.mp4", allowed_extensions={".mp4"})


def test_disallowed_media_extension_rejected() -> None:
    with pytest.raises(UploadValidationError):
        validate_filename("evil.exe", allowed_extensions={".mp4", ".webm", ".mp3"})


def test_malformed_timestamps_rejected() -> None:
    with pytest.raises(TranscriptParseError):
        parse_srt("1\n99:99:99,000 --> 00:00:01,000\nHi\n")


def test_negative_or_inverted_cues_rejected() -> None:
    with pytest.raises(TranscriptParseError):
        parse_srt("1\n00:00:05,000 --> 00:00:01,000\nBackwards\n")
