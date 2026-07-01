"""Restore from backup oskill."""

from __future__ import annotations

import os
import tarfile
import time
from datetime import UTC, datetime
from pathlib import Path

import boto3
from oprim import OprimConnectionError, OprimNotFoundError, OprimValidationError, docker_volume_list
from pydantic import BaseModel


class RestoreResult(BaseModel):
    app_slug: str
    backup_key: str  # S3 object key
    restored_volume: str  # docker volume name
    size_bytes: int
    elapsed_ms: int


def restore_from_backup(
    *,
    app_slug: str,
    backup_bucket: str,
    backup_key: str,  # 指定具体 S3 key
    target_volume: str,  # docker volume name
    temp_dir: str = "/tmp",
    docker_host: str = "unix:///var/run/docker.sock",
    aws_endpoint_url: str | None = None,
    aws_access_key_id: str | None = None,
    aws_secret_access_key: str | None = None,
) -> RestoreResult:
    """从 S3 下载备份并恢复到 docker volume."""
    start_time = time.perf_counter()
    ts = int(datetime.now(UTC).timestamp())
    local_path = Path(temp_dir) / f"{app_slug}-restore-{ts}.tar.gz"

    try:
        # 1. Download from S3
        s3 = boto3.client(
            "s3",
            endpoint_url=aws_endpoint_url,
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key,
        )
        try:
            s3.download_file(backup_bucket, backup_key, str(local_path))
        except Exception as exc:
            raise OprimConnectionError(f"Failed to download backup from S3: {exc}") from exc

        # 2. Get volume mountpoint
        volumes = docker_volume_list(docker_host=docker_host)
        mountpoint = None
        for vol in volumes:
            if vol["name"] == target_volume:
                mountpoint = vol["mountpoint"]
                break

        if not mountpoint:
            raise OprimNotFoundError(f"Target volume not found: {target_volume}")

        # 3. Extract to volume
        if not tarfile.is_tarfile(local_path):
            raise OprimValidationError(f"Downloaded file is not a valid tar archive: {backup_key}")

        size_bytes = local_path.stat().st_size
        try:
            with tarfile.open(local_path) as tar:
                tar.extractall(path=mountpoint)
        except Exception as exc:
            raise OprimValidationError(f"Failed to extract backup to volume: {exc}") from exc

        elapsed_ms = int((time.perf_counter() - start_time) * 1000)
        return RestoreResult(
            app_slug=app_slug,
            backup_key=backup_key,
            restored_volume=target_volume,
            size_bytes=size_bytes,
            elapsed_ms=elapsed_ms,
        )

    finally:
        # 4. Cleanup
        if local_path.exists():
            try:
                os.remove(local_path)
            except OSError:
                pass
