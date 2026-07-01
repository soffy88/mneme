"""
oprim: Shell 执行原子操作
==========================
包含：bash_exec / bash_exec_stream

归属约束
--------
✅ 每个函数 = 单次 subprocess 操作（同步或流式）
✅ bash_exec_stream 是 async 本性（流式 IO 等待）
✅ 失败抛 ShellOprimError（进程本身失败通过返回 code 体现，不抛）

裁决落地
--------
裁决2: bash_exec_stream 改为真正并发读 stdout+stderr
       实现：asyncio.Queue + 两个并发 reader Task，yield 顺序反映真实输出顺序
       不依赖 aiostream 等第三方库
裁决1: OSError on shell spawn / stream timeout 标注 # pragma: no cover
裁决3: detect_language 大小写保持现状（在 text.py）
"""

from __future__ import annotations

import asyncio
import subprocess
from collections.abc import AsyncIterator
from dataclasses import dataclass

from ._exceptions import ShellOprimError

_SENTINEL = object()  # queue 结束哨兵


@dataclass
class ShellResult:
    stdout: str
    stderr: str
    code: int

    @property
    def ok(self) -> bool:
        return self.code == 0


def bash_exec(
    command: str,
    *,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
    timeout: int = 120,
    shell: bool = True,
) -> ShellResult:
    """单次同步执行 shell 命令，返回结构化结果。

    进程退出码非 0 不抛异常（通过 ShellResult.code 体现），仅当
    subprocess 本身无法启动或超时时抛 ShellOprimError。

    Args:
        command: shell 命令字符串。
        cwd: 工作目录；None 使用当前目录。
        env: 环境变量覆盖；None 继承当前环境。
        timeout: 超时秒数，默认 120。
        shell: 是否以 shell 模式运行，默认 True。

    Returns:
        ShellResult(stdout, stderr, code)。

    Raises:
        ShellOprimError: 无法启动进程或超时。

    Example:
        >>> r = bash_exec("echo hello", cwd="/tmp")
        >>> r.stdout
        'hello\\n'
        >>> r.code
        0
    """
    try:
        result = subprocess.run(
            command,
            shell=shell,
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return ShellResult(
            stdout=result.stdout,
            stderr=result.stderr,
            code=result.returncode,
        )
    except FileNotFoundError as e:  # pragma: no cover
        raise ShellOprimError("shell not found", cause=e)
    except subprocess.TimeoutExpired:
        raise ShellOprimError(f"command timed out after {timeout}s: {command[:80]}")
    except OSError as e:  # pragma: no cover
        raise ShellOprimError("cannot execute command", cause=e)


@dataclass
class StreamChunk:
    text: str
    stream: str  # "stdout" or "stderr"


async def bash_exec_stream(
    command: str,
    *,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
    timeout: float = 300.0,
) -> AsyncIterator[StreamChunk]:
    """单次异步流式执行 shell 命令，并发读 stdout+stderr，按真实顺序 yield。

    裁决2 实现：asyncio.Queue + 两个并发 reader Task。
    stdout 和 stderr 被并发读取后放入同一个 queue，主循环按到达顺序 yield，
    不再积压 stderr 到最后（修复原始串联读的已知 bug）。

    async 本性：流式 IO 等待，适合长时间运行的命令（build/test/install）。

    Args:
        command: shell 命令字符串。
        cwd: 工作目录；None 使用当前目录。
        env: 环境变量覆盖；None 继承当前环境。
        timeout: 单行读取超时秒数，默认 300。

    Yields:
        StreamChunk(text, stream) — stream 为 "stdout" 或 "stderr"，
        顺序反映真实输出到达顺序（不再保证 stderr 在后）。

    Raises:
        ShellOprimError: 无法启动进程或读取超时。

    Example:
        >>> async for chunk in bash_exec_stream("pytest -v"):
        ...     print(chunk.text, end="")
    """
    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=env,
        )
    except OSError as e:  # pragma: no cover
        raise ShellOprimError("cannot start process", cause=e)

    queue: asyncio.Queue[StreamChunk | object] = asyncio.Queue()

    async def _reader(stream: asyncio.StreamReader, label: str) -> None:
        """并发 reader Task：逐行读，放入 queue；结束时放哨兵。"""
        try:
            while True:
                try:
                    line = await asyncio.wait_for(stream.readline(), timeout=timeout)
                except asyncio.TimeoutError:  # pragma: no cover
                    # 超时：放 ShellOprimError 到 queue，让主循环抛出
                    await queue.put(
                        ShellOprimError(f"stream timeout after {timeout}s on {label}")
                    )
                    return
                if not line:
                    break
                await queue.put(StreamChunk(text=line.decode(errors="replace"), stream=label))
        finally:
            await queue.put(_SENTINEL)

    # 启动两个并发 reader Task
    stdout_task = asyncio.ensure_future(_reader(proc.stdout, "stdout"))
    stderr_task = asyncio.ensure_future(_reader(proc.stderr, "stderr"))

    finished = 0
    try:
        while finished < 2:
            item = await queue.get()
            if item is _SENTINEL:
                finished += 1
                continue
            if isinstance(item, ShellOprimError):  # pragma: no cover
                stdout_task.cancel()
                stderr_task.cancel()
                raise item
            yield item  # type: ignore[misc]
    finally:
        # 确保进程收割，不泄漏僵尸进程
        await proc.wait()
