"""Auto-split from hicode whl."""

from __future__ import annotations
import asyncio
import base64
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from ._exceptions import FileOprimError, ParseOprimError, ShellOprimError

@dataclass
class HookResult:
    decision: str
    output: str
    exit_code: int

@dataclass
class ImageBlock:
    """Anthropic content block 格式的图片表示。"""
    type: str
    source_type: str
    media_type: str
    data: str
    path: str
    size_bytes: int

@dataclass
class SkillMeta:
    """Skill frontmatter 解析结果（渐进披露第 1 步，不含 body）。"""
    name: str
    description: str
    version: str
    tools: list[str]
    hooks: list[dict]
    tags: list[str]
    raw: dict
    skill_dir: str

async def run_hook(
    command: str,
    *,
    event_json: dict[str, Any],
    timeout: int = 30,
) -> HookResult:
    """单次执行 hook 脚本，stdin 喂事件 JSON，返回结构化决策。

    Hook 脚本约定：
    - stdin 收到事件 JSON
    - stdout 输出 JSON: {"decision": "allow"|"block"|"modify", "output": str}
    - 非零退出码 → decision="block"（保守策略）
    - 超时 → decision="allow"（不因 hook 超时阻塞主流程）

    Args:
        command: hook 脚本命令字符串（shell 模式执行）。
        event_json: 注入 stdin 的事件数据。
        timeout: 超时秒数，默认 30。

    Returns:
        HookResult(decision, output, exit_code)。

    Raises:
        ShellOprimError: 无法启动进程（非超时类错误）。

    Example:
        >>> result = await run_hook("/hooks/pre_tool.sh",
        ...     event_json={"event": "PreToolUse", "tool": "bash_exec"})
        >>> result.decision
        'allow'
    """
    stdin_data = json.dumps(event_json, ensure_ascii=False).encode()

    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError as e:  # pragma: no cover
        raise ShellOprimError(f"cannot start hook: {command}", cause=e)

    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(stdin_data),
            timeout=timeout,
        )
        exit_code = proc.returncode or 0
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        # 超时 → allow（不因 hook 阻塞主流程）
        return HookResult(decision="allow", output="hook timeout", exit_code=-1)

    raw = stdout.decode(errors="replace").strip()

    # 非零退出 → block（保守策略）
    if exit_code != 0:
        return HookResult(decision="block", output=raw or stderr.decode(errors="replace").strip(), exit_code=exit_code)

    # 尝试解析 JSON 输出
    try:
        parsed = json.loads(raw)
        decision = parsed.get("decision", "allow")
        if decision not in ("allow", "block", "modify"):
            decision = "allow"
        return HookResult(decision=decision, output=parsed.get("output", ""), exit_code=exit_code)
    except (json.JSONDecodeError, AttributeError):
        # 非 JSON 输出 → allow，原始输出透传
        return HookResult(decision="allow", output=raw, exit_code=exit_code)
