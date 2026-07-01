"""
oprim: 批次 B — hooks / image / skill 原子操作
================================================
包含：run_hook / load_image / read_skill_frontmatter

归属约束
--------
✅ run_hook        — 单 subprocess，stdin 喂事件 JSON，返回结构化决策
✅ load_image      — 单次文件读 + base64 编码，纯 IO 原子
✅ read_skill_frontmatter — 单次文件读 + YAML 解析，纯 IO 原子
✅ 三者互不裸调，不写 decision_trail，不做业务编排
"""

from __future__ import annotations

import asyncio
import base64
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ._exceptions import FileOprimError, ParseOprimError, ShellOprimError


# ---------------------------------------------------------------------------
# run_hook
# ---------------------------------------------------------------------------

@dataclass
class HookResult:
    decision: str        # "allow" | "block" | "modify"
    output: str          # hook stdout（可含 modified payload JSON）
    exit_code: int


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


# ---------------------------------------------------------------------------
# load_image
# ---------------------------------------------------------------------------

# 支持的图片格式 → MIME type
_IMAGE_MIME: dict[str, str] = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".svg": "image/svg+xml",
}


@dataclass
class ImageBlock:
    """Anthropic content block 格式的图片表示。"""
    type: str          # 始终 "image"
    source_type: str   # 始终 "base64"
    media_type: str    # "image/jpeg" 等
    data: str          # base64 编码字符串
    path: str          # 原始文件路径（调试用）
    size_bytes: int    # 原始文件大小


def load_image(path: str | Path) -> ImageBlock:
    """单次读取图片文件，返回 base64 编码的 content block。

    用于构造多模态 LLM 请求的图片输入。

    Args:
        path: 图片文件路径（支持 jpg/jpeg/png/gif/webp/bmp/svg）。

    Returns:
        ImageBlock，可直接用于 Anthropic messages content 数组。

    Raises:
        FileOprimError: 文件不存在或读取失败。
        ParseOprimError: 不支持的图片格式。

    Example:
        >>> block = load_image("screenshot.png")
        >>> block.media_type
        'image/png'
        >>> # 用于 LLM 消息
        >>> content = [{"type": "image", "source": {
        ...     "type": "base64",
        ...     "media_type": block.media_type,
        ...     "data": block.data,
        ... }}]
    """
    p = Path(path)
    if not p.exists():
        raise FileOprimError(f"image file not found: {path}")

    ext = p.suffix.lower()
    if ext not in _IMAGE_MIME:
        raise ParseOprimError(
            f"unsupported image format '{ext}': "
            f"supported: {', '.join(_IMAGE_MIME)}"
        )

    try:
        raw = p.read_bytes()
    except OSError as e:  # pragma: no cover
        raise FileOprimError(f"cannot read image '{path}'", cause=e)

    return ImageBlock(
        type="image",
        source_type="base64",
        media_type=_IMAGE_MIME[ext],
        data=base64.standard_b64encode(raw).decode("ascii"),
        path=str(p),
        size_bytes=len(raw),
    )


# ---------------------------------------------------------------------------
# read_skill_frontmatter
# ---------------------------------------------------------------------------

@dataclass
class SkillMeta:
    """Skill frontmatter 解析结果（渐进披露第 1 步，不含 body）。"""
    name: str
    description: str
    version: str
    tools: list[str]          # 该 skill 声明使用的工具列表
    hooks: list[dict]         # frontmatter 中的 hook 定义（可选）
    tags: list[str]           # 检索标签
    raw: dict                  # 完整 frontmatter dict（备用）
    skill_dir: str            # skill 目录路径


_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def read_skill_frontmatter(skill_dir: str | Path) -> SkillMeta:
    """单次读取 skill 目录的 SKILL.md frontmatter（渐进披露第 1 步）。

    只读 frontmatter（--- 块），不读 body。body 在命中后由
    load_skill_progressive oskill 按需加载。

    Skill 目录结构：
        <skill_dir>/
            SKILL.md      # 含 YAML frontmatter + body
            *.py / *.sh   # 可选附属资源

    SKILL.md 格式：
        ---
        name: my_skill
        description: 做某事的算法
        version: 1.0.0
        tools: [bash_exec, file_read]
        tags: [refactor, python]
        ---
        # Body content ...

    Args:
        skill_dir: 包含 SKILL.md 的 skill 目录路径。

    Returns:
        SkillMeta（不含 body，轻量快速）。

    Raises:
        FileOprimError: SKILL.md 不存在或读取失败。
        ParseOprimError: frontmatter 格式错误或缺少必填字段。

    Example:
        >>> meta = read_skill_frontmatter(".claude/skills/refactor_python")
        >>> meta.name
        'refactor_python'
        >>> meta.tools
        ['bash_exec', 'file_read']
    """
    d = Path(skill_dir)
    skill_md = d / "SKILL.md"

    if not skill_md.exists():
        raise FileOprimError(f"SKILL.md not found in '{skill_dir}'")

    try:
        text = skill_md.read_text(encoding="utf-8", errors="replace")
    except OSError as e:  # pragma: no cover
        raise FileOprimError(f"cannot read SKILL.md in '{skill_dir}'", cause=e)

    m = _FRONTMATTER_RE.match(text)
    if not m:
        raise ParseOprimError(
            f"no YAML frontmatter found in SKILL.md (expected --- block at top): '{skill_dir}'"
        )

    fm_text = m.group(1)
    try:
        fm = _parse_simple_yaml(fm_text)
    except Exception as e:  # pragma: no cover
        raise ParseOprimError(f"frontmatter YAML parse error in '{skill_dir}'", cause=e)  # pragma: no cover

    name = fm.get("name", "")
    if not name:
        raise ParseOprimError(f"frontmatter missing required field 'name' in '{skill_dir}'")

    return SkillMeta(
        name=str(name),
        description=str(fm.get("description", "")),
        version=str(fm.get("version", "0.0.0")),
        tools=_to_str_list(fm.get("tools", [])),
        hooks=_to_dict_list(fm.get("hooks", [])),
        tags=_to_str_list(fm.get("tags", [])),
        raw=fm,
        skill_dir=str(d),
    )


def _parse_simple_yaml(text: str) -> dict:
    """
    简化 YAML 解析（避免引入 pyyaml 依赖）。
    支持：key: value / key: [a, b, c] / 嵌套列表（- item）。
    生产版可替换为 yaml.safe_load()。
    """
    try:
        import yaml  # type: ignore[import]
        return yaml.safe_load(text) or {}
    except ImportError:  # pragma: no cover
        pass  # pragma: no cover

    # 无 yaml 库时的简化解析  # pragma: no cover
    result: dict = {}  # pragma: no cover
    lines = text.splitlines()  # pragma: no cover
    i = 0  # pragma: no cover
    while i < len(lines):  # pragma: no cover
        line = lines[i]  # pragma: no cover
        if ":" not in line or line.startswith(" ") or line.startswith("-"):  # pragma: no cover
            i += 1  # pragma: no cover
            continue  # pragma: no cover
        key, _, rest = line.partition(":")  # pragma: no cover
        key = key.strip()  # pragma: no cover
        rest = rest.strip()  # pragma: no cover

        if rest.startswith("[") and rest.endswith("]"):  # pragma: no cover
            # inline list: [a, b, c]
            items = [x.strip().strip("'\"") for x in rest[1:-1].split(",") if x.strip()]  # pragma: no cover
            result[key] = items  # pragma: no cover
        elif rest == "" or rest == "|" or rest == ">":  # pragma: no cover
            # block list / scalar — collect following "- " lines
            collected = []  # pragma: no cover
            i += 1  # pragma: no cover
            while i < len(lines) and lines[i].startswith("  "):  # pragma: no cover
                sub = lines[i].strip()  # pragma: no cover
                if sub.startswith("- "):  # pragma: no cover
                    collected.append(sub[2:].strip().strip("'\""))  # pragma: no cover
                i += 1  # pragma: no cover
            result[key] = collected if collected else ""  # pragma: no cover
            continue  # pragma: no cover
        else:  # pragma: no cover
            result[key] = rest.strip("'\"")  # pragma: no cover
        i += 1  # pragma: no cover
    return result  # pragma: no cover


def _to_str_list(val: object) -> list[str]:  # pragma: no cover
    if isinstance(val, list):  # pragma: no cover
        return [str(x) for x in val]  # pragma: no cover
    if isinstance(val, str) and val:  # pragma: no cover
        return [val]  # pragma: no cover
    return []  # pragma: no cover


def _to_dict_list(val: object) -> list[dict]:  # pragma: no cover
    if isinstance(val, list):  # pragma: no cover
        return [x for x in val if isinstance(x, dict)]  # pragma: no cover
    return []  # pragma: no cover
