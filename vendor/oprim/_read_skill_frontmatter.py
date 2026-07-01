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
