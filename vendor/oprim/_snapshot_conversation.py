"""Auto-split from hicode whl."""

from __future__ import annotations
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any
from ._exceptions import OprimError
from ._protocols import PersistenceHandle
from .text import count_tokens

class PromptOprimError(OprimError):
    """prompt 构建 / 消息处理失败。"""

class SnapshotOprimError(OprimError):
    """会话快照失败。"""

@dataclass
class ThinkingResult:
    """扩展思考提取结果。"""
    thinking: str
    text: str
    has_thinking: bool
    thinking_blocks: list[str] = field(default_factory=list)
    text_blocks: list[str] = field(default_factory=list)

@dataclass
class ConversationSnapshot:
    """会话快照结构。"""
    snapshot_id: str
    session_id: str
    message_count: int
    created_at: float
    store_key: str
    revision: str

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
