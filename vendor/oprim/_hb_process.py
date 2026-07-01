"""H-B B组: 进程控制扩展 (5)
spawn_pty / stream_stdout / kill_process / wait_with_timeout / run_background
"""
from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path

from ._exceptions import ShellOprimError


@dataclass
class ProcHandle:
    """普通异步子进程句柄。"""
    pid: int
    _proc: asyncio.subprocess.Process = field(repr=False)


@dataclass
class PtyHandle:
    """PTY 伪终端子进程句柄。"""
    pid: int
    master_fd: int
    _proc: asyncio.subprocess.Process = field(repr=False)


# str UUID4 作 job id
JobId = str

# 全局后台 job 注册表（进程级共享）
_JOBS: dict[str, asyncio.subprocess.Process] = {}


async def spawn_pty(
    cmd: str,
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
) -> PtyHandle:
    """伪终端启动（交互式/需要 TTY 的命令）。

    分配 PTY master/slave，启动 cmd 连接至 slave 端；返回 handle
    供 stream_stdout 读取 master 端输出。

    Args:
        cmd: shell 命令字符串。
        cwd: 工作目录（必须存在）。
        env: 额外环境变量（合并到 os.environ）。

    Returns:
        PtyHandle(pid, master_fd, _proc)。

    Raises:
        ValueError: cmd 为空。
        OSError: PTY 分配失败或平台不支持。
        FileNotFoundError: cwd 不存在。

    Example:
        >>> handle = await spawn_pty("python -i", cwd=Path("/tmp"))
    """
    if not cmd:
        raise ValueError("cmd must not be empty")
    if not Path(cwd).exists():
        raise FileNotFoundError(f"cwd does not exist: {cwd}")

    try:
        import pty as _pty
    except ImportError as e:
        raise OSError("pty module not available on this platform") from e

    env_dict: dict[str, str] = {**os.environ, **(env or {})}
    master_fd, slave_fd = _pty.openpty()

    try:
        proc = await asyncio.create_subprocess_shell(
            cmd,
            cwd=cwd,
            env=env_dict,
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
        )
    finally:
        os.close(slave_fd)

    return PtyHandle(pid=proc.pid, master_fd=master_fd, _proc=proc)


async def stream_stdout(
    handle: PtyHandle | ProcHandle,
) -> AsyncIterator[str]:
    """流式读进程输出（TUI 实时显示）。

    async 生成器；逐块 yield UTF-8 解码文本直到进程/PTY 关闭。

    Args:
        handle: PtyHandle（从 spawn_pty）或 ProcHandle（含 stdout PIPE）。

    Yields:
        解码后的文本块。

    Raises:
        ValueError: handle 类型非法。

    Example:
        >>> async for chunk in stream_stdout(handle):
        ...     print(chunk, end="")
    """
    if isinstance(handle, PtyHandle):
        loop = asyncio.get_event_loop()
        while True:
            try:
                chunk: bytes = await loop.run_in_executor(
                    None, lambda: os.read(handle.master_fd, 4096)
                )
            except OSError:
                break
            if not chunk:
                break
            yield chunk.decode("utf-8", errors="replace")
    elif isinstance(handle, ProcHandle):
        proc = handle._proc
        if proc.stdout is None:
            return
        while True:
            chunk = await proc.stdout.read(4096)
            if not chunk:
                break
            yield chunk.decode("utf-8", errors="replace")
    else:
        raise ValueError(f"unsupported handle type: {type(handle).__name__}")


async def kill_process(
    handle: ProcHandle | PtyHandle,
    *,
    sig: str = "TERM",
) -> None:
    """终止进程（中断/超时），幂等。

    Args:
        handle: ProcHandle 或 PtyHandle。
        sig: 信号名 "TERM"（默认）/ "KILL" / "INT" / "HUP"。

    Raises:
        ValueError: sig 非法。
        PermissionError: 无权限发信号。

    Example:
        >>> await kill_process(handle, sig="TERM")
    """
    sig_map = {
        "TERM": signal.SIGTERM,
        "KILL": signal.SIGKILL,
        "INT": signal.SIGINT,
        "HUP": signal.SIGHUP,
    }
    if sig not in sig_map:
        raise ValueError(f"unsupported signal {sig!r}; valid: {sorted(sig_map)}")

    proc = handle._proc
    if proc.returncode is not None:
        return  # already exited — idempotent

    try:
        pgid = os.getpgid(proc.pid)
        os.killpg(pgid, sig_map[sig])
    except ProcessLookupError:
        pass  # already dead
    except PermissionError:
        raise


async def wait_with_timeout(
    handle: ProcHandle | PtyHandle,
    *,
    timeout: float,
) -> int:
    """等进程结束（带超时），返回 exit_code。

    超时不自动 kill（职责分离，由调用方决定后续 kill_process）。

    Args:
        handle: ProcHandle 或 PtyHandle。
        timeout: 最长等待秒数（必须 > 0）。

    Returns:
        进程退出码。

    Raises:
        ValueError: timeout <= 0。
        TimeoutError: 超时进程未结束。

    Example:
        >>> code = await wait_with_timeout(handle, timeout=30)
    """
    if timeout <= 0:
        raise ValueError(f"timeout must be > 0, got {timeout}")

    proc = handle._proc
    if proc.returncode is not None:
        return proc.returncode

    # asyncio.wait() avoids Python 3.12 wait_for cancellation-propagation hang
    task = asyncio.ensure_future(proc.wait())
    done, _ = await asyncio.wait({task}, timeout=timeout)
    if not done:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        raise TimeoutError(
            f"process {proc.pid} did not finish within {timeout}s"
        )
    return task.result()


async def run_background(
    cmd: str,
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
) -> JobId:
    """后台启动进程，立即返回 job id；不等待完成。

    Args:
        cmd: shell 命令字符串。
        cwd: 工作目录（必须存在）。
        env: 额外环境变量（合并到 os.environ）。

    Returns:
        str UUID4 job id；可经 _JOBS[job_id] 获取底层 Process。

    Raises:
        ValueError: cmd 为空。
        FileNotFoundError: cwd 不存在。
        ShellOprimError: 进程启动失败。

    Example:
        >>> jid = await run_background("sleep 60", cwd=Path("/tmp"))
    """
    if not cmd:
        raise ValueError("cmd must not be empty")
    if not Path(cwd).exists():
        raise FileNotFoundError(f"cwd does not exist: {cwd}")

    env_dict: dict[str, str] = {**os.environ, **(env or {})}

    try:
        proc = await asyncio.create_subprocess_shell(
            cmd,
            cwd=cwd,
            env=env_dict,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except Exception as e:
        raise ShellOprimError(f"run_background failed to start: {cmd[:80]}", cause=e)

    job_id: JobId = str(uuid.uuid4())
    _JOBS[job_id] = proc
    return job_id
