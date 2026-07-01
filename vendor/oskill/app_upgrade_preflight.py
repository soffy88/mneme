"""App upgrade preflight oskill."""

from __future__ import annotations

from oprim import docker_container_inspect, fs_disk_usage, http_request_once
from pydantic import BaseModel

from oskill.backup_schedule_check import backup_schedule_check


class PreflightCheck(BaseModel):
    name: str
    passed: bool
    detail: str | None


class AppUpgradePreflightResult(BaseModel):
    app_slug: str
    target_version: str
    go: bool
    checks: list[PreflightCheck]
    blocking_reason: str | None


def app_upgrade_preflight(
    *,
    app_slug: str,
    target_version: str,
    container_id: str,
    backup_bucket: str,
    s3_prefix: str,
    docker_host: str = "unix:///var/run/docker.sock",
    min_free_gb: float = 5.0,
    aws_endpoint_url: str | None = None,
) -> AppUpgradePreflightResult:
    """Performs 4 checks before an app upgrade."""
    checks: list[PreflightCheck] = []
    go = True
    blocking_reason = None

    # 1. Image Reachable
    # Hit Docker Hub manifest API: https://registry-1.docker.io/v2/{app_slug}/manifests/{target_version}
    # status 200/401 均视为镜像存在
    image_url = f"https://registry-1.docker.io/v2/{app_slug}/manifests/{target_version}"
    try:
        resp = http_request_once(method="GET", url=image_url, timeout_sec=10)
        passed = resp.status_code in (200, 401)
        detail = (
            f"Status code: {resp.status_code}"
            if passed
            else f"Image not found or registry error (status {resp.status_code})"
        )
    except Exception as exc:
        passed = False
        detail = str(exc)

    checks.append(PreflightCheck(name="image_reachable", passed=passed, detail=detail))
    if not passed and go:
        go = False
        blocking_reason = "Target image unreachable"

    # 2. Container Healthy
    try:
        inspect = docker_container_inspect(
            container_id=container_id, docker_host=docker_host
        )
        passed = inspect.state == "running" and (
            inspect.health in (None, "healthy", "starting")
        )
        detail = f"State: {inspect.state}, Health: {inspect.health}"
    except Exception as exc:
        passed = False
        detail = str(exc)

    checks.append(
        PreflightCheck(name="container_healthy", passed=passed, detail=detail)
    )
    if not passed and go:
        go = False
        blocking_reason = "Current container is not healthy"

    # 3. Backup Fresh
    try:
        b_res = backup_schedule_check(
            app_slug=app_slug,
            backup_bucket=backup_bucket,
            s3_prefix=s3_prefix,
            max_age_hours=1,
            aws_endpoint_url=aws_endpoint_url,
        )
        passed = b_res.status == "ok"
        detail = f"Status: {b_res.status}, Age: {b_res.age_hours}h"
    except Exception as exc:
        passed = False
        detail = str(exc)

    checks.append(PreflightCheck(name="backup_fresh", passed=passed, detail=detail))
    if not passed and go:
        go = False
        blocking_reason = "No fresh backup found (last backup > 1h or missing)"

    # 4. Disk Sufficient
    try:
        usage = fs_disk_usage(path="/", docker_host=docker_host)
        free_gb = usage.free_bytes / (1024**3)
        passed = free_gb >= min_free_gb
        detail = f"Free space: {free_gb:.2f} GB"
    except Exception as exc:
        passed = False
        detail = str(exc)

    checks.append(PreflightCheck(name="disk_sufficient", passed=passed, detail=detail))
    if not passed and go:
        go = False
        blocking_reason = f"Insufficient disk space (need {min_free_gb} GB)"

    return AppUpgradePreflightResult(
        app_slug=app_slug,
        target_version=target_version,
        go=go,
        checks=checks,
        blocking_reason=blocking_reason,
    )
