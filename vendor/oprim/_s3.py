"""S3 / object storage oprim — 2 atomic S3 operations."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel

from oprim._exceptions import (
    OprimAuthError,
    OprimConnectionError,
    OprimError,
    OprimNotFoundError,
)

try:
    import boto3  # type: ignore[import-untyped]
    import botocore.exceptions  # type: ignore[import-untyped]
except ImportError:
    boto3 = None  # type: ignore[assignment]
    botocore = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class UploadResult(BaseModel):
    s3_url: str
    etag: str
    size_bytes: int
    elapsed_ms: int


class ObjectMetadata(BaseModel):
    s3_url: str
    exists: bool
    size_bytes: int | None
    etag: str | None
    last_modified: str | None
    content_type: str | None
    storage_class: str | None
    metadata: dict[str, str]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _parse_s3_url(s3_url: str) -> tuple[str, str]:
    """Parse s3://bucket/key → (bucket, key). Raise on bad format."""
    parsed = urlparse(s3_url)
    if parsed.scheme != "s3":
        raise OprimError(f"Invalid S3 URL scheme: {s3_url!r}. Expected s3://bucket/key")
    bucket = parsed.netloc
    key = parsed.path.lstrip("/")
    if not bucket:
        raise OprimError(f"Invalid S3 URL — missing bucket: {s3_url!r}")
    return bucket, key


def _make_s3_client() -> Any:
    if boto3 is None:
        raise OprimError(
            "boto3 is required for S3 oprim. Install with: pip install boto3"
        )

    try:
        return boto3.client("s3")
    except Exception as exc:
        raise OprimConnectionError(f"Failed to create S3 client: {exc}") from exc


# ---------------------------------------------------------------------------
# 10.2 s3_upload_file
# ---------------------------------------------------------------------------

def s3_upload_file(
    *,
    local_path: str,
    s3_url: str,
    content_type: str | None = None,
    sse: str | None = None,
) -> UploadResult:
    """上传本地文件到 S3.

    Args:
        local_path: 本地文件路径
        s3_url: 目标 S3 URL (s3://bucket/key)
        content_type: Content-Type header (可选)
        sse: 服务器端加密 ("AES256" 或 "aws:kms", 可选)

    Returns:
        UploadResult

    Raises:
        OprimNotFoundError: local_path 不存在
        OprimAuthError: AWS credentials 缺失或无效
        OprimConnectionError: S3 不可达
    """
    p = Path(local_path)
    if not p.exists() or not p.is_file():
        raise OprimNotFoundError(f"Local file not found: {local_path}")

    bucket, key = _parse_s3_url(s3_url)
    s3 = _make_s3_client()

    extra_args: dict[str, Any] = {}
    if content_type:
        extra_args["ContentType"] = content_type
    if sse:
        extra_args["ServerSideEncryption"] = sse

    t0 = time.monotonic()
    try:
        s3.upload_file(str(p), bucket, key, ExtraArgs=extra_args if extra_args else None)
        elapsed = int((time.monotonic() - t0) * 1000)

        # Get ETag and size from head_object
        head = s3.head_object(Bucket=bucket, Key=key)
        etag = head.get("ETag", "").strip('"')
        size_bytes = head.get("ContentLength", p.stat().st_size)
    except botocore.exceptions.NoCredentialsError as exc:
        raise OprimAuthError(f"AWS credentials not found: {exc}") from exc
    except botocore.exceptions.ClientError as exc:
        code = exc.response["Error"]["Code"]
        if code in ("InvalidAccessKeyId", "SignatureDoesNotMatch", "403"):
            raise OprimAuthError(f"AWS authentication failed: {exc}") from exc
        raise OprimConnectionError(f"S3 upload failed: {exc}") from exc
    except Exception as exc:
        raise OprimConnectionError(f"Unexpected S3 error: {exc}") from exc

    return UploadResult(
        s3_url=s3_url,
        etag=etag,
        size_bytes=size_bytes,
        elapsed_ms=elapsed,
    )


# ---------------------------------------------------------------------------
# 10.3 s3_object_metadata
# ---------------------------------------------------------------------------

def s3_object_metadata(
    *,
    s3_url: str,
) -> ObjectMetadata:
    """查 S3 对象元数据 (HEAD).

    Args:
        s3_url: S3 URL (s3://bucket/key)

    Returns:
        ObjectMetadata — exists=False 时其他字段为 None

    Raises:
        OprimAuthError / OprimConnectionError
    """
    bucket, key = _parse_s3_url(s3_url)
    s3 = _make_s3_client()

    try:
        head = s3.head_object(Bucket=bucket, Key=key)
    except botocore.exceptions.NoCredentialsError as exc:
        raise OprimAuthError(f"AWS credentials not found: {exc}") from exc
    except botocore.exceptions.ClientError as exc:
        code = exc.response["Error"]["Code"]
        if code == "404" or code == "NoSuchKey":
            return ObjectMetadata(
                s3_url=s3_url,
                exists=False,
                size_bytes=None,
                etag=None,
                last_modified=None,
                content_type=None,
                storage_class=None,
                metadata={},
            )
        if code in ("403", "InvalidAccessKeyId", "SignatureDoesNotMatch"):
            raise OprimAuthError(f"AWS authentication failed: {exc}") from exc
        raise OprimConnectionError(f"S3 head_object failed: {exc}") from exc
    except Exception as exc:
        raise OprimConnectionError(f"Unexpected S3 error: {exc}") from exc

    last_mod = head.get("LastModified")
    if last_mod is not None:
        last_mod = last_mod.isoformat()

    return ObjectMetadata(
        s3_url=s3_url,
        exists=True,
        size_bytes=head.get("ContentLength"),
        etag=head.get("ETag", "").strip('"') or None,
        last_modified=last_mod,
        content_type=head.get("ContentType"),
        storage_class=head.get("StorageClass"),
        metadata=head.get("Metadata") or {},
    )
