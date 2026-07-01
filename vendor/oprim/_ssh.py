"""SSH oprim — execute commands and upload files via SSH."""

from __future__ import annotations

import time

import paramiko
from pydantic import BaseModel

from oprim._exceptions import (
    OprimAuthError,
    OprimConnectionError,
    OprimNotFoundError,
    OprimTimeoutError,
)


class SshExecResult(BaseModel):
    host: str
    stdout: str
    stderr: str
    exit_code: int
    elapsed_ms: int


def ssh_exec(
    *,
    host: str,
    username: str,
    command: str,
    port: int = 22,
    key_path: str | None = None,
    password: str | None = None,
    timeout_sec: int = 30,
) -> SshExecResult:
    """Execute command via SSH."""
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    start_time = time.perf_counter()
    try:
        connect_kwargs = {
            "hostname": host,
            "username": username,
            "port": port,
            "timeout": timeout_sec,
            "banner_timeout": timeout_sec,
        }
        if key_path:
            connect_kwargs["key_filename"] = key_path
        if password:
            connect_kwargs["password"] = password

        client.connect(**connect_kwargs)

        stdin, stdout, stderr = client.exec_command(command, timeout=timeout_sec)
        exit_code = stdout.channel.recv_exit_status()

        result = SshExecResult(
            host=host,
            stdout=stdout.read().decode("utf-8", errors="replace"),
            stderr=stderr.read().decode("utf-8", errors="replace"),
            exit_code=exit_code,
            elapsed_ms=int((time.perf_counter() - start_time) * 1000),
        )
        return result
    except paramiko.AuthenticationException as exc:
        raise OprimAuthError(f"SSH authentication failed for {host}: {exc}") from exc
    except TimeoutError as exc:
        raise OprimTimeoutError(f"SSH connection timeout for {host}: {exc}") from exc
    except (OSError, paramiko.SSHException) as exc:
        raise OprimConnectionError(f"SSH connection failed for {host}: {exc}") from exc
    finally:
        client.close()


class SshUploadResult(BaseModel):
    host: str
    remote_path: str
    size_bytes: int
    elapsed_ms: int


def ssh_file_upload(
    *,
    host: str,
    username: str,
    local_path: str,
    remote_path: str,
    port: int = 22,
    key_path: str | None = None,
    password: str | None = None,
    timeout_sec: int = 30,
) -> SshUploadResult:
    """Upload file via SFTP."""
    import os

    if not os.path.exists(local_path):
        raise OprimNotFoundError(f"Local file not found: {local_path}")

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    start_time = time.perf_counter()
    try:
        connect_kwargs = {
            "hostname": host,
            "username": username,
            "port": port,
            "timeout": timeout_sec,
        }
        if key_path:
            connect_kwargs["key_filename"] = key_path
        if password:
            connect_kwargs["password"] = password

        client.connect(**connect_kwargs)

        sftp = client.open_sftp()
        try:
            sftp.put(local_path, remote_path)
            stat = sftp.stat(remote_path)
            return SshUploadResult(
                host=host,
                remote_path=remote_path,
                size_bytes=stat.st_size,
                elapsed_ms=int((time.perf_counter() - start_time) * 1000),
            )
        finally:
            sftp.close()
    except paramiko.AuthenticationException as exc:
        raise OprimAuthError(f"SSH authentication failed for {host}: {exc}") from exc
    except TimeoutError as exc:
        raise OprimTimeoutError(f"SSH connection timeout for {host}: {exc}") from exc
    except (OSError, paramiko.SSHException) as exc:
        raise OprimConnectionError(f"SSH connection failed for {host}: {exc}") from exc
    finally:
        client.close()


class SshPortCheckResult(BaseModel):
    host: str
    target_port: int
    listening: bool
    error: str | None


def ssh_port_forward_check(
    *,
    host: str,
    username: str,
    target_port: int,
    port: int = 22,
    key_path: str | None = None,
    password: str | None = None,
    timeout_sec: int = 10,
) -> SshPortCheckResult:
    """Check if a port is listening on the remote host via SSH."""
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        connect_kwargs = {
            "hostname": host,
            "username": username,
            "port": port,
            "timeout": timeout_sec,
        }
        if key_path:
            connect_kwargs["key_filename"] = key_path
        if password:
            connect_kwargs["password"] = password

        client.connect(**connect_kwargs)

        command = (
            f"ss -tlnp 2>/dev/null | grep ':{target_port}' || "
            f"netstat -tlnp 2>/dev/null | grep ':{target_port}'"
        )
        stdin, stdout, stderr = client.exec_command(command, timeout=timeout_sec)
        output = stdout.read().decode("utf-8")

        return SshPortCheckResult(
            host=host,
            target_port=target_port,
            listening=f":{target_port}" in output,
            error=None,
        )
    except Exception as exc:
        return SshPortCheckResult(
            host=host,
            target_port=target_port,
            listening=False,
            error=str(exc),
        )
    finally:
        client.close()
