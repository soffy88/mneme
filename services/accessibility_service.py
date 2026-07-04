"""accessibility_service.py — U.23 UDL 无障碍（后端可做的部分）

3O 边界：接请求 → 鉴权 → 读写 users.accessibility_prefs / 调 oprim.text_to_speech →
返回。字体/行距/配色的实际渲染是 mneme-web（真前端）的事，这里只做：
  1. 偏好跨设备持久化（存储 + 读写）
  2. 公式朗读（复用已有 oprim.text_to_speech，把 KU rich_content 展平成可读文本）
  3. 低带宽模式的响应裁剪判定（供各端点按需跳过 SVG/大字段，见 main.py 里的用法）

低带宽模式本身不在这里"生效"——各端点自己决定裁剪什么（H.1 /v1/solve 跳过 SVG
生成、/v1/lesson 和 /v1/knowledge-points 跳过大字段），这里只提供偏好读写。
"""

from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from services.models import KnowledgeUnit, User

_DEFAULT_PREFS = {
    "font_size": "normal",  # small|normal|large|xlarge
    "line_height": "normal",  # normal|relaxed|loose
    "color_scheme": "default",  # default|high_contrast|dark|warm
    "low_bandwidth": False,
}
_ALLOWED_KEYS = set(_DEFAULT_PREFS.keys())


async def get_accessibility_prefs(db: AsyncSession, student_id: uuid.UUID) -> dict:
    row = (
        await db.execute(select(User.accessibility_prefs).where(User.id == student_id))
    ).scalar_one_or_none()
    return {**_DEFAULT_PREFS, **(row or {})}


async def set_accessibility_prefs(
    db: AsyncSession, student_id: uuid.UUID, updates: dict
) -> dict:
    """合并写入（部分更新，未传的字段保留原值）；未知字段拒绝，避免偏好字段无序膨胀。"""
    unknown = set(updates) - _ALLOWED_KEYS
    if unknown:
        return {"error": f"未知偏好字段: {sorted(unknown)}"}

    current = await get_accessibility_prefs(db, student_id)
    merged = {**current, **updates}
    await db.execute(
        update(User).where(User.id == student_id).values(accessibility_prefs=merged)
    )
    await db.commit()
    return merged


def flatten_rich_content(rich_content: Optional[dict]) -> str:
    """把结构各异的 rich_content（按 ku_type 七套 prompt，字段名不固定）展平成
    一段可朗读文本：取所有字符串/字符串列表值，跳过 None/空值，按出现顺序拼接。"""
    if not rich_content:
        return ""
    parts: list[str] = []

    def _walk(value: object) -> None:
        if isinstance(value, str):
            v = value.strip()
            if v:
                parts.append(v)
        elif isinstance(value, list):
            for item in value:
                _walk(item)
        elif isinstance(value, dict):
            for v in value.values():
                _walk(v)

    _walk(rich_content)
    return "。".join(parts)


async def read_aloud_ku(db: AsyncSession, ku_id: str, *, language: str = "zh") -> dict:
    """公式朗读：取 KU 的 rich_content（讲透内容）展平成文本，调 TTS 合成语音。
    没有 rich_content 时退回 description/name，仍拿不到文本则 not_available。"""
    from oprim import text_to_speech

    ku = (
        await db.execute(select(KnowledgeUnit).where(KnowledgeUnit.id == ku_id))
    ).scalar_one_or_none()
    if ku is None:
        return {"error": "not_found"}

    text = flatten_rich_content(ku.rich_content)
    if not text:
        text = (ku.description or ku.name or "").strip()
    if not text:
        return {"ku_id": ku_id, "available": False, "reason": "该知识点暂无可朗读内容"}

    # text_to_speech 内部经 ProviderRegistry.get().generic("tts", provider) 解析 caller，
    # 不接受调用方传 caller（同 speaking_service.wrap_tts 用法）。
    audio_b64 = await text_to_speech(text=text, language=language, provider="default")
    return {"ku_id": ku_id, "available": True, "text": text, "audio_b64": audio_b64}
