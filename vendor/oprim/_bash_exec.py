"""Auto-split from hicode whl."""

from __future__ import annotations
import asyncio
import subprocess
from collections.abc import AsyncIterator
from dataclasses import dataclass
from ._exceptions import ShellOprimError

@dataclass
class ShellResult:
    stdout: str
    stderr: str
    code: int

    @property
    def ok(self) -> bool:
        return self.code == 0

@dataclass
class StreamChunk:
    text: str
    stream: str

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
