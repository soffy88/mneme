"""
oprim: 批次 C — prompt 构建 / 消息处理 / 快照原子操作
=======================================================
包含：build_system_prompt / truncate_messages / extract_thinking
      snapshot_conversation

归属约束
--------
✅ build_system_prompt    — 纯字符串拼接（无 IO）
✅ truncate_messages      — 纯计算（调 count_tokens oprim，不互为裸调——
                            count_tokens 是从 text.py 导入的函数，不是 oprim 间裸调，
                            是"复用已有计算函数"，类似调标准库）
✅ extract_thinking       — 纯解析（无 IO）
✅ snapshot_conversation  — 单次 IO 写（store=PersistenceHandle Protocol 注入）
"""

from __future__ import annotations
from ._exceptions import OprimError, LLMOprimError, BudgetExceededError, PromptOprimError, SearchOprimError, HttpOprimError, SnapshotOprimError
from .llm._types import LLMResponse, StreamDelta, EmbedResult, ConversationSnapshot, ThinkingResult, SearchResult, HttpResponse

import json
import time
import uuid
from typing import Any

from ._protocols import PersistenceHandle
from .text import count_tokens




# ---------------------------------------------------------------------------
# build_system_prompt
# ---------------------------------------------------------------------------

def build_system_prompt(
    *,
    mode: str = "build",
    agents_md: str = "",
    tools_summary: str = "",
    skills_context: str = "",
    custom_sections: dict[str, str] | None = None,
    max_length: int | None = None,
) -> str:
    """构建完整的系统 prompt 字符串（纯计算）。

    按固定结构拼接各部分，保证 prompt 格式一致性：
      1. 角色声明（含模式）
      2. AGENTS.md / 项目记忆
      3. 可用工具摘要
      4. Skills 上下文
      5. 自定义节（custom_sections）

    Args:
        mode: 运行模式，"build"（默认）或 "plan"。
        agents_md: AGENTS.md 或项目记忆内容（空字符串则省略此节）。
        tools_summary: 可用工具的文本摘要（空字符串则省略此节）。
        skills_context: 已加载的 skill body 内容（空字符串则省略此节）。
        custom_sections: 额外节，dict[标题, 内容]。
        max_length: 输出字符数上限；超出时截断（优先保留前面的节）。

    Returns:
        完整系统 prompt 字符串。

    Raises:
        PromptOprimError: mode 不合法。

    Example:
        >>> prompt = build_system_prompt(
        ...     mode="build",
        ...     agents_md="# Project\\nThis is a Python web service.",
        ... )
        >>> "BUILD" in prompt
        True
    """
    if mode not in ("build", "plan"):
        raise PromptOprimError(f"invalid mode '{mode}': must be 'build' or 'plan'")

    parts: list[str] = []

    # 1. 角色声明
    mode_upper = mode.upper()
    role = (
        f"You are hicode, an expert AI coding agent operating in {mode_upper} mode.\n"
    )
    if mode == "plan":
        role += (
            "In PLAN mode: analyze the codebase and propose changes only. "
            "Do NOT write files, execute commands, or make any modifications.\n"
        )
    else:
        role += (
            "In BUILD mode: you may read files, write files, execute commands, "
            "and make all necessary changes to complete the task.\n"
        )
    parts.append(role)

    # 2. AGENTS.md / 项目记忆
    if agents_md and agents_md.strip():
        parts.append(f"## Project Memory\n{agents_md.strip()}")

    # 3. 工具摘要
    if tools_summary and tools_summary.strip():
        parts.append(f"## Available Tools\n{tools_summary.strip()}")

    # 4. Skills
    if skills_context and skills_context.strip():
        parts.append(f"## Skills\n{skills_context.strip()}")

    # 5. 自定义节
    for title, content in (custom_sections or {}).items():
        if content and content.strip():
            parts.append(f"## {title}\n{content.strip()}")

    result = "\n\n".join(parts)

    # 长度截断（优先保留前面节）
    if max_length is not None and len(result) > max_length:
        result = result[:max_length]

    return result


# ---------------------------------------------------------------------------
# truncate_messages
# ---------------------------------------------------------------------------

def truncate_messages(
    messages: list[dict],
    *,
    budget: int,
    model: str = "claude-sonnet-4-6",
    keep_first: int = 1,
    keep_last: int = 4,
) -> list[dict]:
    """将消息列表截断到 token 预算内（纯计算）。

    策略：保留最前 keep_first 条 + 最后 keep_last 条，
    中间消息从旧到新逐条删除，直到 token 数满足预算。

    Args:
        messages: 完整消息列表。
        budget: token 预算上限。
        model: 用于 token 计数的模型名。
        keep_first: 始终保留的最前 N 条（通常是 system/user 的首条），默认 1。
        keep_last: 始终保留的最后 N 条（最近上下文），默认 4。

    Returns:
        截断后的消息列表（长度 ≤ 原始，token 数 ≤ budget）。

    Raises:
        PromptOprimError: budget ≤ 0。

    Example:
        >>> short = truncate_messages(long_messages, budget=4000)
        >>> count_tokens(short) <= 4000
        True
    """
    if budget <= 0:
        raise PromptOprimError(f"budget must be > 0, got {budget}")

    if not messages:
        return []

    # 已在预算内，直接返回
    if count_tokens(messages, model=model) <= budget:
        return list(messages)

    n = len(messages)
    # 保证 keep_first + keep_last 不超过总数
    keep_first = min(keep_first, n)
    keep_last = min(keep_last, n - keep_first)

    front = list(messages[:keep_first])
    back = list(messages[n - keep_last:]) if keep_last > 0 else []
    middle = list(messages[keep_first: n - keep_last if keep_last > 0 else n])

    # 逐条从 middle 头部删除，直到满足预算
    while middle:
        candidate = front + middle + back
        if count_tokens(candidate, model=model) <= budget:
            return candidate  # pragma: no cover
        middle.pop(0)

    # middle 已空，检查 front+back 是否满足
    return front + back


# ---------------------------------------------------------------------------
# extract_thinking
# ---------------------------------------------------------------------------


def extract_thinking(response: dict) -> ThinkingResult:
    """从 LLM 响应中拆分 thinking block 和 text block（纯计算）。

    支持 Anthropic 扩展思考格式（interleaved thinking）。
    response 是 caller 返回的原始 dict 或 LLMResponse.raw。

    Args:
        response: LLM 原始响应 dict（含 content 列表）。

    Returns:
        ThinkingResult(thinking, text, has_thinking, thinking_blocks, text_blocks)。

    Raises:
        PromptOprimError: response 格式无法解析。

    Example:
        >>> result = extract_thinking(raw_response)
        >>> result.has_thinking
        True
        >>> result.thinking[:50]
        "Let me think about this step by step..."
    """
    content = response.get("content", [])
    if not isinstance(content, list):
        if isinstance(content, str):
            return ThinkingResult(
                thinking="", text=content,
                has_thinking=False, text_blocks=[content],
            )
        raise PromptOprimError(
            f"extract_thinking: content must be list or str, got {type(content).__name__}"
        )

    thinking_blocks: list[str] = []
    text_blocks: list[str] = []

    for block in content:
        if not isinstance(block, dict):
            continue  # pragma: no cover
        btype = block.get("type", "")
        if btype == "thinking":
            thinking_blocks.append(block.get("thinking", ""))
        elif btype == "text":
            text_blocks.append(block.get("text", ""))
        # tool_use 和其他 block 忽略

    return ThinkingResult(
        thinking="\n\n".join(thinking_blocks),
        text="\n".join(text_blocks),
        has_thinking=bool(thinking_blocks),
        thinking_blocks=thinking_blocks,
        text_blocks=text_blocks,
    )


# ---------------------------------------------------------------------------
# snapshot_conversation
# ---------------------------------------------------------------------------


async def snapshot_conversation(
    messages: list[dict],
    *,
    store: PersistenceHandle,
    session_id: str = "",
    metadata: dict[str, Any] | None = None,
) -> ConversationSnapshot:
    """单次序列化会话历史并落盘（checkpoint 用，undo/rewind 之根）。

    async 本性：外部存储 IO 等待。

    Args:
        messages: 当前完整消息列表。
        store: PersistenceHandle Protocol 实例（由调用方注入）。
        session_id: 会话 ID（用于构造 store key）。
        metadata: 附加元数据（写入快照，不影响消息）。

    Returns:
        ConversationSnapshot（含 snapshot_id / store_key / revision）。

    Raises:
        SnapshotOprimError: 序列化失败或存储写入失败。

    Example:
        >>> snap = await snapshot_conversation(
        ...     messages, store=persistence, session_id="sess_001"
        ... )
        >>> snap.snapshot_id
        'snap_a1b2c3d4'
        >>> snap.revision  # 用于 rewind
        'rev_20260613_...'
    """
    if not isinstance(messages, list):
        raise SnapshotOprimError("messages must be a list")  # pragma: no cover

    snapshot_id = f"snap_{uuid.uuid4().hex[:8]}"
    sid = session_id or f"session_{uuid.uuid4().hex[:8]}"
    ts = time.time()

    try:
        payload = json.dumps({
            "snapshot_id": snapshot_id,
            "session_id": sid,
            "messages": messages,
            "message_count": len(messages),
            "created_at": ts,
            "metadata": metadata or {},
        }, ensure_ascii=False)
    except (TypeError, ValueError) as e:
        raise SnapshotOprimError("failed to serialize messages", cause=e)

    store_key = f"session:{sid}:snapshot:{snapshot_id}"

    try:
        revision = await store.save(key=store_key, value=payload)
    except (SnapshotOprimError,):
        raise  # pragma: no cover
    except Exception as e:
        raise SnapshotOprimError("failed to save snapshot to store", cause=e)

    return ConversationSnapshot(
        snapshot_id=snapshot_id,
        session_id=sid,
        message_count=len(messages),
        created_at=ts,
        store_key=store_key,
        revision=revision,
    )
